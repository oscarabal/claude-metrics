"""Index of Claude Code's conversation files (~/.claude/projects), read incrementally and in the background.

Only metadata is kept: timestamps, models, token counts, tool and skill names, compactions and the title of
each session. The text of the conversations is never stored. Costs come from the telemetry in Loki, matched
by request id, because the conversation files carry tokens but no cost.
"""
import calendar
import hashlib
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

from coach import errors as coach_errors

ROOT = os.environ.get("PROJECTS_DIR", "/projects")
LOKI_URL = os.environ.get("LOKI_URL", "http://loki:3100")
SCAN_SECONDS = int(os.environ.get("SCAN_SECONDS", "30"))
# Optional folders that hold one project per subfolder ("C:\\Workspace;~/code"): a session started deeper inside
# one of them still counts for the first subfolder. Without it the project is the last folder of the session's cwd.
PROJECT_ROOTS = [r.strip().replace("\\", "/").rstrip("/").lower()
                 for r in re.split(r"[;,]", os.environ.get("PROJECT_ROOTS", "")) if r.strip()]

_TS = re.compile(r'"timestamp":"([^"]+)"')
# anchored: a real command message opens with its tags, while text that merely quotes them (a compaction summary, a pasted example) does not
_COMMAND = re.compile(r"\s*(?:<command-message>[^<]*</command-message>\s*)?<command-name>/?([^<\s]+)</command-name>")


_CWD = re.compile(r'"cwd":"((?:[^"\\]|\\.)*)"')
# A worktree belongs to the repository it was created from
_WORKTREE = re.compile(r"/\.claude/worktrees/.*$|/\.worktrees/.*$", re.I)
# A home folder or a drive root is not a project: sessions opened there count as "otros"
_NOT_PROJECT = re.compile(r"^(?:[a-z]:)?(?:/(?:users|home)/[^/]+|/root|/var/root)?$", re.I)
_FOLDER_PROJECT = {}


def project_from_cwd(cwd):
    """The project of a working directory: the first subfolder below a PROJECT_ROOTS entry, else its last folder."""
    path = _WORKTREE.sub("", cwd.replace("\\", "/").rstrip("/"))
    if _NOT_PROJECT.match(path):
        return "otros"
    low = path.lower()
    for root in PROJECT_ROOTS:
        if low.startswith(root + "/"):
            return path[len(root) + 1:].split("/")[0].lower()
    return (path.rsplit("/", 1)[-1] or "otros").lower()


def _cwd_in(base):
    """The working directory recorded in the conversation files of a folder (all of them share it)."""
    try:
        names = sorted(n for n in os.listdir(base) if n.endswith(".jsonl"))
    except OSError:
        return ""
    for name in names:
        try:
            with open(os.path.join(base, name), encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f):
                    m = _CWD.search(line)
                    if m:
                        return json.loads('"%s"' % m.group(1))
                    if i >= 50:
                        break
        except (OSError, ValueError):
            continue
    return ""


def project_of(folder):
    """Project of a ~/.claude/projects folder, from the cwd its sessions recorded. The folder name alone is
    ambiguous (Claude Code turns every separator, dot and space into a dash), so it is only a last resort."""
    project = _FOLDER_PROJECT.get(folder)
    if project is None:
        cwd = _cwd_in(os.path.join(ROOT, folder))
        if cwd:
            project = _FOLDER_PROJECT[folder] = project_from_cwd(cwd)
        else:  # no cwd yet (empty folder or a file still being written): ask again on the next scan
            m = re.search(r"Workspace-(.+?)(--|$)", folder)
            project = m.group(1).lower() if m else "otros"
    return project


def ts_ms(text):
    """'2026-11-15T11:50:13.196Z' -> milliseconds since the epoch."""
    try:
        base = calendar.timegm(time.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")) * 1000
        return base + (int(text[20:23]) if len(text) >= 23 and text[19] == "." else 0)
    except (ValueError, TypeError):
        return 0


def _text_of(content):
    """The text of a message or tool result content, which is a string or a list of blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def new_session(sid, project):
    return {"id": sid, "project": project, "title": "", "cwd": "", "branch": "", "created": 0, "updated": 0,
            "msgs": {},          # message id -> [ts, model, input, output, cache_read, cache_create, sidechain, request id, skill]
            "commands": [],      # (ts, name)
            "command_prompts": {},  # prompt id -> (ts, command name): the turn each command launched
            "skills": [],        # (ts, name)
            "compactions": [],   # (ts, tokens before, tokens after, trigger)
            "tools": {},         # name -> [calls, errors]
            "tool_ids": {},      # tool_use id -> name
            "errored": set(), "seen_commands": set(), "agents": set(),
            # for the improvement report (coach): metadata of each tool call and of each turn, never their text
            "calls": {},         # tool_use id -> [ts, tool, model, turn, arg hash, status, error class, sidechain]
            "turns": {},         # turn id (the user prompt that started it) -> ts
            "interrupts": [],    # (ts, turn) when the user stopped an answer
            "cur_turn": {}}      # file (main thread or subagent) -> turn id being answered


class Index:
    def __init__(self):
        self.lock = threading.Lock()
        self.offsets = {}
        self.sessions = {}
        self.costs = {}          # request id -> USD, from Loki
        self.requests = {}       # request id -> (prompt id, model, query source, USD), from Loki
        self.request_ts = {}     # request id -> ms, from Loki, so the coach's store can date each cost
        self.request_meta = {}   # request id -> (session id, effort, output tokens), from Loki, for the report's filters
        # (tool_use id, "result" or "decision") -> (ms, session id, tool, bytes returned, decision, decision source);
        # never the tool parameters, which the events also carry
        self.tool_events = {}
        self.loki_ns = 0
        self.tool_ns = 0
        self.done = False
        self.loki_ok = False

    # ---------------------------------------------------------------- conversation files
    def _session_for(self, path):
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/").split("/")
        project, sub = rel[0], "subagents" in rel
        sid = rel[1] if sub else rel[-1][:-6]
        s = self.sessions.get(sid)
        if s is None:
            s = self.sessions[sid] = new_session(sid, project_of(project))
        return s, sub, (rel[-1][:-6] if sub else "")

    def _line(self, s, line, sub, agent):
        stamp = _TS.search(line)
        when = ts_ms(stamp.group(1)) if stamp else 0
        if when:
            s["created"] = when if not s["created"] or when < s["created"] else s["created"]
            s["updated"] = max(s["updated"], when)
        if agent:
            s["agents"].add(agent)
        if line.startswith('{"type":"custom-title"'):
            try:
                s["title"] = json.loads(line).get("customTitle") or s["title"]
            except ValueError:
                pass
            return
        if '"type":"assistant"' in line:
            try:
                j = json.loads(line)
            except ValueError:
                return
            if j.get("type") != "assistant":
                return
            m = j.get("message") or {}
            u = m.get("usage") or {}
            mid = m.get("id") or j.get("uuid")
            rec = [when, m.get("model") or "unknown", u.get("input_tokens", 0) or 0, u.get("output_tokens", 0) or 0,
                   u.get("cache_read_input_tokens", 0) or 0, u.get("cache_creation_input_tokens", 0) or 0,
                   bool(sub or j.get("isSidechain")), j.get("requestId"), j.get("attributionSkill"),
                   s["cur_turn"].get(agent)]
            old = s["msgs"].get(mid)
            if old is None or rec[3] >= old[3]:  # a message is logged once per content block; keep the fullest usage
                s["msgs"][mid] = rec
            s["cwd"] = s["cwd"] or j.get("cwd", "")
            s["branch"] = s["branch"] or j.get("gitBranch", "")
            for block in m.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id") not in s["tool_ids"]:
                    name = block.get("name") or "?"
                    s["tool_ids"][block["id"]] = name
                    entry = s["tools"].setdefault(name, [0, 0])
                    entry[0] += 1
                    if name == "Skill" and isinstance(block.get("input"), dict) and block["input"].get("skill"):
                        s["skills"].append((when, block["input"]["skill"]))
                    try:  # the arguments are only hashed, to recognise the same call repeated
                        args = json.dumps(block.get("input"), sort_keys=True)
                    except (TypeError, ValueError):
                        args = ""
                    s["calls"][block["id"]] = [when, name, rec[1], rec[9], hashlib.sha1((name + "\0" + args).encode("utf-8", "replace")).hexdigest()[:12],
                                               None, None, rec[6]]
            return
        if '"type":"user"' in line:
            try:
                j = json.loads(line)
            except ValueError:
                return
            if j.get("type") != "user":
                return
            content = (j.get("message") or {}).get("content")
            if isinstance(content, str) and "<command-name>" in content:
                found = _COMMAND.match(content)
                if found and j.get("uuid") not in s["seen_commands"]:
                    s["seen_commands"].add(j.get("uuid"))
                    s["commands"].append((when, found.group(1)))
                    if j.get("promptId"):
                        s["command_prompts"][j["promptId"]] = (when, found.group(1))
            results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"] if isinstance(content, list) else []
            for block in results:
                tid = block.get("tool_use_id")
                call = s["calls"].get(tid)
                text = _text_of(block.get("content"))
                if block.get("is_error"):
                    if tid not in s["errored"]:
                        s["errored"].add(tid)
                        name = s["tool_ids"].get(tid)
                        if name:
                            s["tools"].setdefault(name, [0, 0])[1] += 1
                    if call is not None:
                        # the error text is read only to pick a class and is not kept
                        call[5], call[6] = "error", coach_errors.classify(text, call[1])
                elif call is not None:
                    call[5] = "ok"
            if results:
                return
            text = content if isinstance(content, str) else _text_of(content)
            if "[Request interrupted by user" in text:
                s["interrupts"].append((when, s["cur_turn"].get(agent)))
                return
            if j.get("isMeta") or text.lstrip().startswith(("<local-command", "<command-message>")) and "<command-name>" not in text:
                return
            if text.strip() or isinstance(content, list):
                turn = j.get("promptId") or j.get("uuid")
                if turn and turn not in s["turns"]:
                    s["turns"][turn] = when
                s["cur_turn"][agent] = turn
            return
        if '"compactMetadata"' in line and '"type":"system"' in line:
            try:
                j = json.loads(line)
            except ValueError:
                return
            meta = j.get("compactMetadata") or {}
            s["compactions"].append((when, meta.get("preTokens", 0), meta.get("postTokens", 0), meta.get("trigger", "")))

    def scan_files(self):
        for folder, _dirs, names in os.walk(ROOT):
            for name in names:
                if not name.endswith(".jsonl"):
                    continue
                path = os.path.join(folder, name)
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                offset = self.offsets.get(path, 0)
                if size < offset:
                    offset = 0
                if size == offset:
                    continue
                try:
                    with open(path, "rb") as f:
                        f.seek(offset)
                        chunk = f.read(size - offset)
                except OSError:
                    continue
                end = chunk.rfind(b"\n") + 1  # a line still being written is left for the next round
                if not end:
                    continue
                with self.lock:
                    s, sub, agent = self._session_for(path)
                    for raw in chunk[:end].split(b"\n"):
                        if raw:
                            self._line(s, raw.decode("utf-8", "replace"), sub, agent)
                self.offsets[path] = offset + end
        self.done = True

    # ---------------------------------------------------------------- costs from the telemetry
    def scan_costs(self):
        now = int(time.time() * 1e9)
        start = self.loki_ns + 1 if self.loki_ns else now - 30 * 86400 * 10 ** 9
        while True:
            url = LOKI_URL + "/loki/api/v1/query_range?" + urllib.parse.urlencode({
                "query": '{service_name=~".+"} | event_name="api_request"', "limit": 5000, "start": start, "end": now, "direction": "forward"})
            with urllib.request.urlopen(url, timeout=20) as r:
                streams = json.load(r)["data"]["result"]
            count, last = 0, start
            for stream in streams:
                meta = stream.get("stream", {})
                for ts, _line in stream.get("values", []):
                    count += 1
                    last = max(last, int(ts))
                    try:
                        self.costs[meta["request_id"]] = float(meta["cost_usd"])
                        self.requests[meta["request_id"]] = (meta.get("prompt_id", ""), meta.get("model", "unknown"),
                                                             meta.get("query_source", "unknown"), float(meta["cost_usd"]))
                        self.request_ts[meta["request_id"]] = int(ts) // 1_000_000
                        self.request_meta[meta["request_id"]] = (meta.get("session_id", ""), meta.get("effort", ""),
                                                                 int(float(meta.get("output_tokens") or 0)))
                    except (KeyError, ValueError):
                        pass
            self.loki_ns = max(self.loki_ns, last)
            self.loki_ok = True
            if count < 5000:
                return
            start = last + 1

    def scan_tool_events(self):
        """tool_result and tool_decision events since the last read: tool, session, bytes and decision only."""
        now = int(time.time() * 1e9)
        start = self.tool_ns + 1 if self.tool_ns else now - 30 * 86400 * 10 ** 9
        while True:
            url = LOKI_URL + "/loki/api/v1/query_range?" + urllib.parse.urlencode({
                "query": '{service_name=~".+"} | event_name=~"tool_result|tool_decision"', "limit": 5000,
                "start": start, "end": now, "direction": "forward"})
            with urllib.request.urlopen(url, timeout=20) as r:
                streams = json.load(r)["data"]["result"]
            count, last = 0, start
            for stream in streams:
                meta = stream.get("stream", {})
                for ts, _line in stream.get("values", []):
                    count += 1
                    last = max(last, int(ts))
                    kind = "result" if meta.get("event_name") == "tool_result" else "decision"
                    key = (meta.get("tool_use_id") or "%s:%s" % (meta.get("session_id", ""), ts), kind)
                    try:
                        size = int(float(meta.get("tool_result_size_bytes") or 0))
                    except ValueError:
                        size = 0
                    with self.lock:
                        self.tool_events[key] = (int(ts) // 1_000_000, meta.get("session_id", ""), meta.get("tool_name", "?"),
                                                 size, meta.get("decision", ""), meta.get("source", ""))
            self.tool_ns = max(self.tool_ns, last)
            if count < 5000:
                return
            start = last + 1

    def run(self):
        costs_at = 0
        while True:
            try:
                self.scan_files()
            except Exception:  # the next round retries
                pass
            if time.time() - costs_at > 60:
                try:
                    self.scan_costs()
                except Exception:
                    pass
                try:
                    self.scan_tool_events()
                except Exception:
                    pass
                costs_at = time.time()
            time.sleep(SCAN_SECONDS)

    # ---------------------------------------------------------------- reads
    def snapshot(self):
        with self.lock:
            return {sid: s for sid, s in self.sessions.items()}

    def cost_of(self, msg):
        return self.costs.get(msg[7]) if msg[7] else None


INDEX = Index()


def start():
    threading.Thread(target=INDEX.run, daemon=True).start()
