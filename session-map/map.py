"""Exporter and pages for Claude Code's sessions.

Publishes which project each session belongs to (what the dashboards filter by), the context of the most
recent sessions with the time of their last activity (the dashboard keeps those inside its time range), the skills and commands used, and serves the list and the detail of the sessions.
It reads the conversation files read-only, in the background, and keeps only metadata (see index.py).
"""
import calendar
import json
import os
import re
import threading
import time
import urllib.parse
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

import index
import pages
import report_page
from coach import metrics as coach_metrics, render as coach_render, report as coach_report

PORT = int(os.environ.get("PORT", "9100"))
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://localhost:3000/d/claude-code")
CONTEXT_SESSIONS = int(os.environ.get("CONTEXT_SESSIONS", "30"))
CONTEXT_LIMIT_DEFAULT = int(os.environ.get("CONTEXT_LIMIT_DEFAULT", "200000"))
CONTEXT_LIMITS = os.environ.get("CONTEXT_LIMITS", "")  # "model=tokens,..."

_TYPES = ("input", "cache_read", "cache_write", "output")


def esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def day_of(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


def human(n):
    return ("%.2f" % (n / 1_000_000)).rstrip("0").rstrip(".") + "M" if n >= 1_000_000 else "%dk" % round(n / 1000)


def limit_for(model, seen=0):
    """(limit, assumed). Configured per model; otherwise the default, raised to 1M when the session has already used more than the default."""
    for item in filter(None, (x.strip() for x in CONTEXT_LIMITS.split(","))):
        key, _, val = item.partition("=")
        if key.strip() == model and val.strip().isdigit():
            return int(val), False
    if seen > CONTEXT_LIMIT_DEFAULT:  # a window cannot be exceeded, so a bigger context proves a bigger window
        return max(1_000_000, seen), True
    return CONTEXT_LIMIT_DEFAULT, True


def peak_context(s):
    return max((m[2] + m[3] + m[4] + m[5] for m in s["msgs"].values() if not m[6]), default=0)


def tokens_of(m):
    return {"input": m[2], "cache_read": m[4], "cache_write": m[5], "output": m[3]}


def last_main(s):
    best = None
    for m in s["msgs"].values():
        if not m[6] and (m[2] + m[3] + m[4] + m[5]) > 0 and (best is None or m[0] >= best[0]):
            best = m
    return best


def collect():
    out = []
    add = out.append
    ix = index.INDEX
    with ix.lock:
        sessions = list(ix.sessions.values())
        # Listed from the folders, so the project map is complete from the first scrape, before the index has read the files
        known = {}
        for folder in os.listdir(index.ROOT):
            base = os.path.join(index.ROOT, folder)
            if os.path.isdir(base):
                for name in os.listdir(base):
                    if name.endswith(".jsonl"):
                        known[name[:-6]] = index.project_of(folder)
        for s in sessions:
            known.setdefault(s["id"], s["project"])
        add("# TYPE claude_session_project gauge")
        for sid, project in known.items():
            add('claude_session_project{session_id="%s",project="%s"} 1' % (esc(sid), esc(project)))

        add("# TYPE claude_context_tokens gauge")
        add("# TYPE claude_context_limit_tokens gauge")
        add("# TYPE claude_session_updated_seconds gauge")
        recent = sorted((s for s in sessions if last_main(s)), key=lambda s: -s["updated"])[:CONTEXT_SESSIONS]
        for s in recent:
            m = last_main(s)
            limit, _ = limit_for(m[1], peak_context(s))
            name = (s["title"][:48] + "…") if len(s["title"]) > 48 else s["title"]
            shown = "%s · %s (%s, %s)" % (s["project"], name or s["id"][:8], m[1], human(limit))
            lab = 'session="%s",label="%s",project="%s",model="%s"' % (esc(s["id"]), esc(shown), esc(s["project"]), esc(m[1]))
            for t, v in tokens_of(m).items():
                add('claude_context_tokens{%s,type="%s"} %s' % (lab, t, v))
            add("claude_context_limit_tokens{%s} %s" % (lab, limit))
            add('claude_session_updated_seconds{session="%s"} %d' % (esc(s["id"]), s["updated"] // 1000))

        uses, costs, created, days = {}, {}, {}, set()
        for s in sessions:
            if s["created"] and any(m[2] + m[3] + m[4] + m[5] > 0 for m in s["msgs"].values()):  # empty sessions are not counted, as in the list
                key = (day_of(s["created"]), s["project"])
                created[key] = created.get(key, 0) + 1
                days.add(key[0])
            for ts, name in s["commands"]:
                k = (day_of(ts), name, s["project"], "command")
                uses[k] = uses.get(k, 0) + 1
                days.add(k[0])
            for ts, name in s["skills"]:
                k = (day_of(ts), name, s["project"], "skill")
                uses[k] = uses.get(k, 0) + 1
                days.add(k[0])
            for m in s["msgs"].values():
                cost = ix.cost_of(m)
                if m[8] and cost is not None:
                    k = (day_of(m[0]), m[8], s["project"])
                    costs[k] = costs.get(k, 0) + cost
                    days.add(k[0])
        # cost of the turns each command launched (they share its prompt id), split by model and by origin: main thread, subagents, background calls
        launched = {}
        for s in sessions:
            for pid, (ts, name) in s["command_prompts"].items():
                launched[pid] = (day_of(ts), name, s["project"])
        by_command = {}
        for pid, model, origin, cost in list(ix.requests.values()):
            hit = launched.get(pid)
            if hit:
                k = hit + (model, origin)
                by_command[k] = by_command.get(k, 0) + cost
                days.add(hit[0])
        add("# TYPE claude_day_sessions gauge")
        for (day, proj), n in created.items():
            add('claude_day_sessions{day="%s",project="%s"} %s' % (day, esc(proj), n))
        add("# TYPE claude_day_skill_uses gauge")
        for (day, name, proj, kind), n in uses.items():
            add('claude_day_skill_uses{day="%s",skill="%s",project="%s",kind="%s"} %s' % (day, esc(name), esc(proj), kind, n))
        add("# TYPE claude_day_skill_cost_usd gauge")
        for (day, name, proj), v in costs.items():
            add('claude_day_skill_cost_usd{day="%s",skill="%s",project="%s"} %s' % (day, esc(name), esc(proj), v))
        add("# TYPE claude_day_command_cost_usd gauge")
        for (day, name, proj, model, origin), v in by_command.items():
            add('claude_day_command_cost_usd{day="%s",command="%s",project="%s",model="%s",origin="%s"} %s' % (day, esc(name), esc(proj), esc(model), esc(origin), v))
        days |= coach_metrics.days()  # days of the improvement series, so the dashboard's day filter finds them
        add("# TYPE claude_day_start_seconds gauge")
        for day in sorted(days):
            y, mo, d = (int(x) for x in day.split("-"))
            add('claude_day_start_seconds{day="%s"} %s' % (day, calendar.timegm((y, mo, d, 0, 0, 0))))
    add("# TYPE claude_index_scan_complete gauge")
    add("claude_index_scan_complete %s" % (1 if ix.done else 0))
    add("# TYPE claude_index_cost_requests gauge")
    add("claude_index_cost_requests %s" % len(ix.costs))
    out.extend(coach_metrics.lines())  # cached by the coach's background thread; nothing is computed here
    return "\n".join(out) + "\n"


def detail(sid):
    ix = index.INDEX
    with ix.lock:
        s = ix.sessions.get(sid)
        if not s:
            return None
        msgs = list(s["msgs"].values())
        main = []
        for m in sorted((m for m in msgs if not m[6]), key=lambda m: m[0]):
            if m[2] + m[3] + m[4] + m[5] > 0:
                main.append({"t": m[0], "model": m[1], "tokens": tokens_of(m), "cost": ix.cost_of(m), "skill": m[8]})
        models, attributed, known_cost, known_n = {}, {}, 0.0, 0
        sub = {"agents": len(s["agents"]), "messages": 0, "tokens": 0, "cost": 0.0}
        tokens_total = 0
        for m in msgs:
            tok = m[2] + m[3] + m[4] + m[5]
            if tok == 0:
                continue
            cost = ix.cost_of(m)
            row = models.setdefault(m[1], [0, 0, 0.0, 0])
            row[0] += 1
            row[1] += tok
            tokens_total += tok
            if cost is not None:
                row[2] += cost
                row[3] += 1
                known_cost += cost
                known_n += 1
                if m[8]:
                    attributed[m[8]] = attributed.get(m[8], 0) + cost
            if m[6]:
                sub["messages"] += 1
                sub["tokens"] += tok
                sub["cost"] += cost or 0
        skills = {}
        for _, name in s["commands"]:
            skills.setdefault(name, [0, 0])[0] += 1
        for _, name in s["skills"]:
            skills.setdefault(name, [0, 0])[1] += 1
        last = None
        limit, assumed = CONTEXT_LIMIT_DEFAULT, True
        if main:
            m = main[-1]
            last = dict(m["tokens"], model=m["model"])
            limit, assumed = limit_for(m["model"], peak_context(s))
        tools = {k: list(v) for k, v in s["tools"].items()}
        data = {"id": s["id"], "title": s["title"], "project": s["project"], "branch": s["branch"], "created": s["created"], "updated": s["updated"],
                "main": main, "models": models, "tools": tools, "skills": skills, "attributed": attributed, "compactions": sorted(s["compactions"]),
                "sub": sub, "last": last, "limit": limit,
                "limit_note": ("Límite supuesto; defínelo con CONTEXT_LIMITS en .env." if assumed else ""),
                "cost_known": known_cost, "msgs_known": known_n, "msgs_total": sum(1 for m in msgs if m[2] + m[3] + m[4] + m[5] > 0), "tokens_total": tokens_total}
    return data


def listing(since_ms, until_ms, projects):
    ix = index.INDEX
    rows = []
    with ix.lock:
        for s in ix.sessions.values():
            if not s["created"] or not (since_ms <= s["created"] <= until_ms):
                continue
            if projects and s["project"] not in projects:
                continue
            tokens, cost, known, models = 0, 0.0, 0, {}
            n = 0
            for m in s["msgs"].values():
                tok = m[2] + m[3] + m[4] + m[5]
                if tok == 0:
                    continue
                n += 1
                tokens += tok
                models[m[1]] = models.get(m[1], 0) + 1
                c = ix.cost_of(m)
                if c is not None:
                    cost += c
                    known += 1
            if not n:
                continue
            main_model = max(models, key=models.get) if models else "—"
            rows.append((s["id"], s["title"], s["project"], main_model, n, tokens, cost if known else None, s["created"], s["updated"], len(s["agents"])))
    rows.sort(key=lambda r: -r[8])
    return rows


def list_range(query):
    def num(key, default):
        try:
            return int(query.get(key, [default])[0])
        except ValueError:
            return default
    window = num("window", 36500)
    now = int(time.time() * 1000)
    if window > 0 and "from" not in query:
        return now - window * 86400 * 1000, now, ("de los últimos %d días" % window) if window < 36500 else "de todo el historial"
    start, end = num("from", 0), num("to", now)
    # the dashboard sends seconds (period selectors) or milliseconds (Grafana's time picker)
    start, end = (start, end) if start > 10 ** 11 or end > 10 ** 11 else (start * 1000, end * 1000 + 86399000)
    return start, end, "del %s al %s (UTC)" % (day_of(start), day_of(end))


# Reports already built, so the Grafana panels that read /coach/... (several per dashboard load) share one build
_REPORTS, _REPORTS_LOCK = {}, threading.Lock()
REPORT_CACHE_SECONDS = 120


def report_for(query):
    """The improvement report for a query string (window or from/to, project, anon), cached for two minutes."""
    since, until, label = list_range(query)
    label = label.replace("de los ", "").replace("de todo el historial", "todo el historial")
    projects = {p for p in re.split(r"[,|]", ",".join(query.get("project", []))) if p and p not in (".*", "All", "$__all")}
    anon = query.get("anon", ["0"])[0] == "1"
    key = (since // 60000, until // 60000, tuple(sorted(projects)), anon)
    now = time.time()
    with _REPORTS_LOCK:
        hit = _REPORTS.get(key)
        if hit and now - hit[0] < REPORT_CACHE_SECONDS:
            return hit[1]
    data = coach_report.build(index.INDEX, since, until, label, projects or None, anon)
    with _REPORTS_LOCK:
        _REPORTS[key] = (now, data)
        for k in [k for k, (t, _d) in _REPORTS.items() if now - t >= REPORT_CACHE_SECONDS]:
            del _REPORTS[k]
    return data


def _plain(text):
    """Finding text without Markdown marks, for Grafana tables."""
    return re.sub(r"[`*]", "", text or "")


def coach_rows(name, r):
    """Rows of one part of the report as a JSON array, for Grafana's Infinity datasource. None if unknown."""
    findings = r["findings"]
    if name == "summary":
        sev = Counter(f["severity"] for f in findings)
        return [{"hallazgos": len(findings), "alta": sev["alta"], "media": sev["media"], "baja": sev["baja"],
                 "impacto_usd": round(sum(f.get("impact_usd") or 0 for f in findings), 2),
                 "desde": r["period"]["from"], "hasta": r["period"]["to"]}]
    if name == "findings":
        return [{"id": f["id"], "severidad": f["severity"], "regla": "%s %s" % (f["detector"], coach_report.RULES.get(f["detector"], "")),
                 "hallazgo": _plain(f["title"]), "impacto_usd": f.get("impact_usd"), "casos": f.get("impact_count"),
                 "evidencia": _plain(f["evidence"]), "recomendacion": _plain(f["recommendation"])} for f in findings]
    if name == "rules":
        rows = {}
        for f in findings:
            row = rows.setdefault(f["detector"], {"regla": "%s %s" % (f["detector"], coach_report.RULES.get(f["detector"], "")),
                                                  "hallazgos": 0, "alta": 0, "impacto_usd": 0.0})
            row["hallazgos"] += 1
            row["alta"] += f["severity"] == "alta"
            row["impacto_usd"] = round(row["impacto_usd"] + (f.get("impact_usd") or 0), 2)
        return sorted(rows.values(), key=lambda x: (-x["impacto_usd"], -x["hallazgos"]))
    if name == "tool_bytes":
        return [{"herramienta": t["tool"], "resultados": t["results"], "bytes_medios": t["avg_bytes"], "bytes_max": t["max_bytes"],
                 "bytes_total": t["total_bytes"], "tokens_aprox": t["total_bytes"] // 4} for t in r["tables"]["events"]["tool_bytes"]]
    return None


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, ctype):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        try:
            if parsed.path.startswith("/session/"):
                sid = parsed.path[len("/session/"):].strip("/")
                data = detail(sid) if re.fullmatch(r"[A-Za-z0-9\-_]+", sid) else None
                page = pages.render_detail(data, DASHBOARD_URL) if data else pages.not_found(DASHBOARD_URL)
                return self._send(200 if data else 404, page, "text/html; charset=utf-8")
            if parsed.path.rstrip("/") == "/report":
                return self._report_view(parsed)
            if parsed.path.rstrip("/") in ("/report.md", "/report.json"):
                return self._report(parsed)
            if parsed.path.startswith("/coach/"):
                rows = coach_rows(parsed.path[len("/coach/"):].strip("/"), report_for(urllib.parse.parse_qs(parsed.query)))
                if rows is None:
                    return self._send(404, "[]", "application/json")
                return self._send(200, json.dumps(rows, ensure_ascii=False), "application/json; charset=utf-8")
            if parsed.path.rstrip("/") == "/sessions":
                query = urllib.parse.parse_qs(parsed.query)
                since, until, label = list_range(query)
                projects = {p for p in re.split(r"[,|]", ",".join(query.get("project", []))) if p and p not in (".*", "All", "$__all")}
                rows = listing(since, until, projects)
                note = "Sesiones creadas %s%s." % (label, ", proyecto: " + ", ".join(sorted(projects)) if projects else "")
                return self._send(200, pages.render_list(rows, DASHBOARD_URL, note), "text/html; charset=utf-8")
            return self._send(200, collect(), "text/plain; version=0.0.4")
        except Exception as ex:  # report the failure instead of an empty answer
            return self._send(500, "Error: %s\n" % ex, "text/plain; charset=utf-8")

    def _report(self, parsed):
        """The improvement report for the dashboard's time range and projects, to download and share with an AI."""
        as_json = parsed.path.rstrip("/").endswith(".json")
        data = report_for(urllib.parse.parse_qs(parsed.query))
        body = (coach_render.render_json(data) if as_json else coach_render.render(data)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8" if as_json else "text/markdown; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="claude-code-informe-%s.%s"' % (time.strftime("%Y-%m-%d"), "json" if as_json else "md"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _report_view(self, parsed):
        """The improvement report as a web page, opened from the dashboard, with a button to download its Markdown."""
        query = urllib.parse.parse_qs(parsed.query)
        anon = query.get("anon", ["0"])[0] == "1"
        other = {k: v for k, v in query.items() if k != "anon"}
        if not anon:
            other["anon"] = ["1"]
        try:
            md = coach_render.render(report_for(query))
        except Exception as ex:
            return self._send(500, report_page.error("Error: %s" % ex, DASHBOARD_URL), "text/html; charset=utf-8")
        filename = "claude-code-informe-%s.md" % time.strftime("%Y-%m-%d")
        download = "/report.md" + ("?" + parsed.query if parsed.query else "")
        page = report_page.render(md, filename, DASHBOARD_URL, download, anon, "?" + urllib.parse.urlencode(other, doseq=True))
        return self._send(200, page, "text/html; charset=utf-8")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    coach_metrics.start(index.INDEX)  # restores stored costs first, then runs the coach's background work
    index.start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
