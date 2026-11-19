"""Usage analysis for the improvement report (Claude Code).

`build()` reads session-map's index (with the requests and tool events it reads from Loki) and the
inventory of commands and skills, and returns a plain dict. `/report.md`, `/report.json`, the
command line, the Grafana series and the MCP endpoint all start from this dict.

The dict follows the same contract as the OpenCode module (`format_version`, `source`, the same
top-level keys and the same rule ids where a rule means the same), so both can be read alike.

Nothing here reads the text of the conversation: tool errors arrive already reduced to a class.
"""
import time
from collections import Counter, defaultdict

from . import inventory
from . import store as coach_store
from .errors import ADVICE, NOT_AVOIDABLE

FORMAT_VERSION = 1
SOURCE = "claude-code"

RULES = {
    "D1": "Errores de herramienta", "D2": "Coste por modelo u origen", "D3": "Bucles y exploración", "D4": "Contexto",
    "D5": "Permisos", "D6": "Caché", "D7": "Skills", "D8": "Modelo fijado en comandos", "D9": "Interrupciones",
    "D10": "Comandos sin uso", "C1": "Effort", "C2": "Consumo de fondo", "C3": "Resultados grandes",
    "C4": "Planes rechazados", "C5": "Peticiones de permiso", "C6": "Contexto inicial",
}

NOT_LOOPS = {"TodoWrite", "AskUserQuestion", "mcp__ccd_turn__update_plan"}
HIGH_EFFORT = {"high", "xhigh", "max"}
BACKGROUND_HINTS = ("suggest", "title", "summar", "compact", "hook", "classif", "topic", "memory", "quota")


def _pct(a, b):
    return (a / b) if b else 0.0


def _quantile(values, q):
    if not values:
        return 0
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))]


def _day(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


def origin_kind(source):
    """query_source as seen in the telemetry: `sdk` or `repl_main_thread` is the main thread, `agent:...` a subagent,
    `web_search_tool` and the like calls made inside a tool, `prompt_suggestion` or `compact` background work."""
    s = (source or "").lower()
    if any(h in s for h in BACKGROUND_HINTS):
        return "fondo"
    if s.startswith("agent") or "subagent" in s or "task" in s:
        return "subagentes"
    if s.startswith("web_") or s.endswith("_tool") or "_apply" in s:
        return "herramientas"
    return "principal"


# ----------------------------------------------------------------------------- data

def snapshot(ix):
    """A consistent copy of what the report needs from the index, taken under its lock."""
    with ix.lock:
        sessions = []
        for s in ix.sessions.values():
            sessions.append({
                "id": s["id"], "project": s["project"], "created": s["created"], "title": s["title"],
                "msgs": [list(m) for m in s["msgs"].values()],
                "calls": [list(c) for c in s.get("calls", {}).values()],
                "compactions": list(s["compactions"]), "commands": list(s["commands"]),
                "command_prompts": dict(s["command_prompts"]), "skills": list(s["skills"]),
                "turns": dict(s.get("turns", {})), "interrupts": list(s.get("interrupts", [])),
            })
        costs = dict(ix.costs)
        # one row per request and per tool event seen in the telemetry, with its session, for section 6
        requests = []
        for rid, (_pid, model, source, cost) in ix.requests.items():
            sid, effort, out = ix.request_meta.get(rid, (None, "", 0))
            requests.append((ix.request_ts.get(rid, 0), sid, model, effort, source, cost, out))
        tool_events = [(kind,) + tuple(v) for (_tid, kind), v in ix.tool_events.items()]
    return sessions, costs, {"requests": requests, "tools": tool_events}


class Period:
    def __init__(self, sessions, costs, since, until, keep):
        self.since, self.until = since, until
        inside = lambda t: since <= (t or 0) <= until
        self.sessions = [s for s in sessions if keep(s["project"])]
        self.msgs, self.calls, self.compactions, self.commands, self.skill_uses = [], [], [], [], []
        self.turns, self.interrupts, self.first_ctx = {}, [], []
        self.command_turn = {}
        self.turn_cost, self.turn_tokens = defaultdict(float), defaultdict(int)
        self.known, self.total_msgs = 0, 0
        for s in self.sessions:
            sid = s["id"]
            main = sorted((m for m in s["msgs"] if not m[6] and m[2] + m[3] + m[4] + m[5] > 0), key=lambda m: m[0])
            if main and inside(main[0][0]):
                self.first_ctx.append(main[0][2] + main[0][4] + main[0][5])
            for m in s["msgs"]:
                tok = m[2] + m[3] + m[4] + m[5]
                if tok == 0 or not inside(m[0]):
                    continue
                cost = costs.get(m[7]) if m[7] else None
                turn = m[9] if len(m) > 9 else None
                self.msgs.append({"ts": m[0], "model": m[1], "inp": m[2], "out": m[3], "cr": m[4], "cw": m[5], "side": m[6],
                                  "cost": cost, "skill": m[8], "turn": (sid, turn), "sid": sid, "tokens": tok})
                self.total_msgs += 1
                if cost is not None:
                    self.known += 1
                    self.turn_cost[(sid, turn)] += cost
                self.turn_tokens[(sid, turn)] += tok
            for c in s["calls"]:
                if inside(c[0]) and c[5]:
                    self.calls.append({"ts": c[0], "tool": c[1], "model": c[2], "turn": (sid, c[3]), "arg": c[4],
                                       "status": c[5], "cls": c[6], "side": c[7], "sid": sid})
            for comp in s["compactions"]:
                if inside(comp[0]):
                    self.compactions.append((comp[0], comp[1], comp[2], comp[3], sid))
            for ts, name in s["commands"]:
                if inside(ts):
                    self.commands.append((ts, name, sid))
            for ts, name in s["skills"]:
                if inside(ts):
                    self.skill_uses.append((ts, name, sid))
            for pid, (ts, name) in s["command_prompts"].items():
                if inside(ts):
                    self.command_turn[(sid, pid)] = name
            for turn, ts in s["turns"].items():
                if inside(ts):
                    self.turns[(sid, turn)] = ts
            for ts, turn in s["interrupts"]:
                if inside(ts):
                    self.interrupts.append((ts, sid))
        self.turn_starts = defaultdict(list)
        for (sid, _turn), ts in self.turns.items():
            self.turn_starts[sid].append(ts)

    def summary(self):
        m = self.msgs
        cost = sum(x["cost"] or 0 for x in m)
        inp, cr, cw = sum(x["inp"] for x in m), sum(x["cr"] for x in m), sum(x["cw"] for x in m)
        out = sum(x["out"] for x in m)
        errors = sum(1 for c in self.calls if c["status"] == "error")
        sessions = sum(1 for s in self.sessions if self.since <= (s["created"] or 0) <= self.until and s["msgs"])
        return {
            "cost_usd": round(cost, 4), "cost_coverage": round(_pct(self.known, self.total_msgs), 4),
            "tokens": inp + cr + cw + out, "tokens_input": inp, "tokens_cache_read": cr, "tokens_cache_write": cw, "tokens_output": out,
            "cache_hit": round(_pct(cr, inp + cr + cw), 4), "sessions": sessions, "turns": len(self.turns),
            "assistant_messages": len(m), "tool_calls": len(self.calls), "tool_errors": errors,
            "tool_error_rate": round(_pct(errors, len(self.calls)), 4), "compactions": len(self.compactions),
            "aborted": len(self.interrupts),
        }


def build(ix, since, until, label, projects=None, anon=False, now=None, data=None):
    """The report as a dict. `since`/`until` in Unix milliseconds; `projects` a set of names or None."""
    started = time.time()
    sessions, costs, telemetry = data or snapshot(ix)
    keep = (lambda p: p in projects) if projects else (lambda p: True)
    first = min((m[0] for s in sessions for m in s["msgs"] if m[0]), default=since)
    since = max(since, first - first % 86400000)
    span = until - since
    cur = Period(sessions, costs, since, until, keep)
    prev = Period(sessions, costs, since - span, since - 1, keep) if since - span >= first - 86400000 else None

    names = {}
    if anon:
        for i, p in enumerate(sorted({s["project"] for s in cur.sessions}), 1):
            names[p] = "proyecto-%d" % i
    pname = lambda p: names.get(p, p)

    summary = cur.summary()
    st = coach_store.get()
    events = telemetry_tables(telemetry, cur, since, until, bool(projects), st)
    tables = {
        "agents": origins_table(cur),
        "models": models_table(cur),
        "projects": projects_table(cur, pname),
        "tools": tools_table(cur),
        "tool_errors": tool_errors_table(cur),
        "turns": turns_stats(cur),
        "context": context_stats(cur),
        "skills": skills_table(cur),
        "interaction": interaction_stats(cur),
        "model_health": model_health(cur),
        "events": events,
    }
    config = config_inventory(tables["skills"])
    ctx = {"cur": cur, "summary": summary, "tables": tables, "config": config, "pname": pname,
           # cost per tool call where cost is known: dividing by every call would count the calls made before the telemetry
           "avg_call_cost": _pct(summary["cost_usd"], summary["tool_calls"] * summary["cost_coverage"]), "days": round(span / 86400000)}
    findings = []
    for detector in DETECTORS:
        findings.extend(detector(ctx))
    for f in findings:
        f["severity"] = severity(f, summary)
    order = {"alta": 0, "media": 1, "baja": 2}
    findings.sort(key=lambda f: (order[f["severity"]], -(f.get("impact_usd") or 0), -(f.get("impact_count") or 0)))
    for i, f in enumerate(findings, 1):
        f["id"] = "H%d" % i
    return {
        "format_version": FORMAT_VERSION,
        "source": SOURCE,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now or time.time())),
        "period": {"label": label, "from": _day(since), "to": _day(until), "days": round(span / 86400000)},
        "projects": sorted(pname(p) for p in projects) if projects else "todos",
        "anonymized": anon,
        "summary": summary,
        "previous": prev.summary() if prev else None,
        "findings": findings,
        "tables": tables,
        "config": config,
        "build_seconds": round(time.time() - started, 2),
    }


# ----------------------------------------------------------------------------- tables

def origins_table(p):
    """Main thread against subagents, the closest Claude Code has to OpenCode's agents."""
    rows = defaultdict(lambda: {"messages": 0, "cost_usd": 0.0, "output": 0, "models": Counter(), "cost_cmd": 0.0,
                                "msgs_cmd": 0, "models_free": Counter()})
    for m in p.msgs:
        r = rows["subagentes" if m["side"] else "principal"]
        c = m["cost"] or 0
        r["messages"] += 1
        r["cost_usd"] += c
        r["output"] += m["out"]
        r["models"][m["model"]] += c or 1e-9
        if m["turn"] in p.command_turn:
            r["cost_cmd"] += c
            r["msgs_cmd"] += 1
        else:
            r["models_free"][m["model"]] += c or 1e-9
    total = sum(r["cost_usd"] for r in rows.values())
    return [{"agent": k, "messages": r["messages"], "cost_usd": round(r["cost_usd"], 4), "cost_share": round(_pct(r["cost_usd"], total), 4),
             "cost_per_message": round(_pct(r["cost_usd"], r["messages"]), 4), "output_per_message": round(_pct(r["output"], r["messages"])),
             "top_models": [x for x, _ in r["models"].most_common(3)], "cost_in_commands": round(r["cost_cmd"], 4),
             "cost_outside_commands": round(r["cost_usd"] - r["cost_cmd"], 4), "messages_outside_commands": r["messages"] - r["msgs_cmd"],
             "top_models_outside_commands": [x for x, _ in r["models_free"].most_common(3)]}
            for k, r in sorted(rows.items(), key=lambda x: -x[1]["cost_usd"])]


def models_table(p):
    rows = defaultdict(Counter)
    for m in p.msgs:
        r = rows[m["model"]]
        r["messages"] += 1
        r["cost"] += m["cost"] or 0
        r["known"] += 1 if m["cost"] is not None else 0
        r["inp"] += m["inp"]
        r["cr"] += m["cr"]
        r["cw"] += m["cw"]
        r["out"] += m["out"]
        r["tok_known"] += m["tokens"] if m["cost"] is not None else 0
    total = sum(r["cost"] for r in rows.values())
    return [{"provider": "anthropic", "model": k, "messages": r["messages"], "cost_usd": round(r["cost"], 4),
             "cost_share": round(_pct(r["cost"], total), 4), "tokens": r["inp"] + r["cr"] + r["cw"] + r["out"],
             "usd_per_mtok": round(_pct(r["cost"], r["tok_known"]) * 1e6, 3), "cache_hit": round(_pct(r["cr"], r["inp"] + r["cr"] + r["cw"]), 4),
             "input_uncached": r["inp"], "cost_coverage": round(_pct(r["known"], r["messages"]), 4), "messages_with_cost": r["known"]}
            for k, r in sorted(rows.items(), key=lambda x: (-x[1]["cost"], -x[1]["messages"]))]


def projects_table(p, pname):
    rows = defaultdict(Counter)
    proj = {s["id"]: s["project"] for s in p.sessions}
    for m in p.msgs:
        r = rows[proj.get(m["sid"], "otros")]
        r["messages"] += 1
        r["cost"] += m["cost"] or 0
    return [{"project": pname(k), "messages": r["messages"], "cost_usd": round(r["cost"], 4)}
            for k, r in sorted(rows.items(), key=lambda x: -x[1]["cost"])]


def tools_table(p):
    rows = defaultdict(lambda: {"calls": 0, "errors": 0, "classes": Counter()})
    for c in p.calls:
        r = rows[c["tool"]]
        r["calls"] += 1
        if c["status"] == "error":
            r["errors"] += 1
            r["classes"][c["cls"]] += 1
    return [{"tool": t, "calls": r["calls"], "errors": r["errors"], "error_rate": round(_pct(r["errors"], r["calls"]), 4),
             "main_error": r["classes"].most_common(1)[0][0] if r["classes"] else None}
            for t, r in sorted(rows.items(), key=lambda x: -x[1]["calls"])]


def tool_errors_table(p):
    calls, errs, sess = Counter(), Counter(), defaultdict(Counter)
    for c in p.calls:
        calls[(c["tool"], c["model"])] += 1
        if c["status"] == "error":
            k = (c["tool"], c["cls"], c["model"])
            errs[k] += 1
            sess[k][c["sid"]] += 1
    return [{"tool": t, "error_class": cl, "model": mo, "errors": n, "calls_tool_model": calls[(t, mo)],
             "rate": round(_pct(n, calls[(t, mo)]), 4), "sessions": [s for s, _ in sess[(t, cl, mo)].most_common(5)]}
            for (t, cl, mo), n in errs.most_common()]


def turns_stats(p):
    turns = defaultdict(list)
    for c in sorted(p.calls, key=lambda c: c["ts"]):
        turns[c["turn"] + (c["side"],)].append(c)
    sizes = [len(v) for v in turns.values()]
    loops, streaks = [], []
    for key, cs in turns.items():
        keys = Counter(c["arg"] for c in cs if c["tool"] not in NOT_LOOPS)
        repeated = sum(n - 1 for n in keys.values() if n >= 3)
        if repeated:
            tool = Counter(c["tool"] for c in cs if keys[c["arg"]] >= 3).most_common(1)[0][0]
            loops.append({"turn": key[1], "session": cs[0]["sid"], "tool": tool, "repeated_calls": repeated})
        run = best = 0
        for c in cs:
            run = run + 1 if c["status"] == "error" and c["cls"] not in NOT_AVOIDABLE else 0
            best = max(best, run)
        if best >= 3:
            streaks.append({"turn": key[1], "session": cs[0]["sid"], "consecutive_errors": best})
    p95 = _quantile(sizes, 0.95)
    limit = max(40, p95)
    longs = [{"turn": k[1], "session": v[0]["sid"], "tool_calls": len(v), "cost_usd": p.turn_cost.get(k[:2], 0),
              "main_tool": Counter(c["tool"] for c in v).most_common(1)[0][0]} for k, v in turns.items() if len(v) > limit]
    longs.sort(key=lambda x: -x["tool_calls"])
    return {"turns_with_tools": len(sizes), "p50": _quantile(sizes, 0.5), "p90": _quantile(sizes, 0.9), "p95": p95,
            "max": max(sizes) if sizes else 0, "long_limit": limit,
            "loops": sorted(loops, key=lambda x: -x["repeated_calls"]),
            "error_streaks": sorted(streaks, key=lambda x: -x["consecutive_errors"]), "long_turns": longs}


def context_stats(p):
    per = Counter(c[4] for c in p.compactions)
    manual = sum(1 for c in p.compactions if (c[3] or "").lower() == "manual")
    return {"compactions": len(p.compactions), "manual": manual, "auto": len(p.compactions) - manual,
            "sessions_with_compaction": len(per),
            "sessions_2plus": [{"session": s, "compactions": n} for s, n in per.most_common() if n >= 2],
            "compaction_cost_usd": 0.0, "overflow_by_model": [],
            "initial_context_p50": _quantile(p.first_ctx, 0.5), "initial_context_p90": _quantile(p.first_ctx, 0.9),
            "initial_context_sessions": len(p.first_ctx)}


def skills_table(p):
    rows = defaultdict(lambda: {"activations": 0, "cost": 0.0, "tokens": 0})
    for _ts, name, _sid in p.commands:
        rows[("command", name)]["activations"] += 1
    for turn, name in p.command_turn.items():
        r = rows[("command", name)]
        r["cost"] += p.turn_cost.get(turn, 0)
        r["tokens"] += p.turn_tokens.get(turn, 0)
    for _ts, name, _sid in p.skill_uses:
        rows[("skill", name)]["activations"] += 1
    for m in p.msgs:  # Claude Code marks the messages that belong to a skill or command (attributionSkill)
        if m["skill"]:
            if ("command", m["skill"]) in rows and ("skill", m["skill"]) not in rows:
                continue  # a command's cost is already the cost of the turn it launched
            r = rows[("skill", m["skill"])]
            r["cost"] += m["cost"] or 0
            r["tokens"] += m["tokens"]
    names = Counter(n for _k, n in rows)
    return [{"kind": k, "name": n, "activations": r["activations"], "errors": 0, "cost_usd": round(r["cost"], 4),
             "cost_per_activation": round(_pct(r["cost"], r["activations"]), 4), "tokens": r["tokens"],
             "tokens_per_activation": round(_pct(r["tokens"], r["activations"])), "main_agent": None,
             "same_name_as_other_kind": names[n] > 1}
            for (k, n), r in sorted(rows.items(), key=lambda x: (-x[1]["cost"], -x[1]["activations"])) if r["activations"]]


def interaction_stats(p):
    quick = 0
    quick_sessions = set()
    for ts, sid in p.interrupts:
        nxt = [t for t in p.turn_starts.get(sid, []) if t > ts]
        if nxt and min(nxt) - ts <= 120000:
            quick += 1
            quick_sessions.add(sid)
    plans = [c for c in p.calls if c["tool"] == "ExitPlanMode"]
    rejected = sum(1 for c in plans if c["cls"] == "plan_rejected")
    per_session = Counter(sid for sid, _t in p.turns)
    sub_cost = sum(m["cost"] or 0 for m in p.msgs if m["side"])
    total = sum(m["cost"] or 0 for m in p.msgs)
    return {"aborted": len(p.interrupts), "aborted_by_agent": {}, "aborted_quick_retry": quick,
            "aborted_quick_retry_cost_usd": 0.0, "aborted_quick_retry_sessions": sorted(quick_sessions)[:5],
            "user_messages_per_session_p50": _quantile(list(per_session.values()), 0.5),
            "user_messages_per_session_p90": _quantile(list(per_session.values()), 0.9),
            "subagent_sessions": len({m["sid"] for m in p.msgs if m["side"]}),  # sessions that used subagents
            "subagent_cost_share": round(_pct(sub_cost, total), 4),
            "plans": len(plans), "plans_rejected": rejected, "message_errors": {}}


def model_health(p):
    calls, errs = defaultdict(Counter), defaultdict(Counter)
    for c in p.calls:
        calls[c["model"]][c["tool"]] += 1
        if c["status"] == "error" and c["cls"] not in NOT_AVOIDABLE:
            errs[c["model"]][c["tool"]] += 1
    msgs = Counter(m["model"] for m in p.msgs)
    out = {}
    for model in set(msgs) | set(calls):
        tools = [{"tool": t, "errors": n, "calls": calls[model][t], "rate": round(_pct(n, calls[model][t]), 4)} for t, n in errs[model].most_common()]
        out[model] = {"messages": msgs[model], "tool_calls": sum(calls[model].values()), "tool_errors": sum(errs[model].values()),
                      "tools": tools, "message_errors": {}, "message_error_rate": 0.0}
    return out


def telemetry_tables(telemetry, cur, since, until, by_project, st):
    """Effort, query sources, bytes returned by tools and permission decisions, from each request and tool event
    in the telemetry, with the same filter as the rest of the report: the period to the millisecond and, when a
    project is chosen, only the sessions of that project. Without a project filter it also counts the calls of
    sessions whose conversation files are not here (another machine, deleted files)."""
    ids = {s["id"] for s in cur.sessions}
    keep = (lambda sid: sid in ids) if by_project else (lambda sid: True)
    inside = lambda t: since <= (t or 0) <= until
    effort, sources = defaultdict(Counter), defaultdict(Counter)
    days, first, without_meta = set(), None, 0
    for ts, sid, model, eff, src, cost, out in telemetry["requests"]:
        first = ts if ts and (first is None or ts < first) else first
        if not inside(ts):
            continue
        if sid is None:
            without_meta += 1
            if by_project:
                continue
        elif not keep(sid):
            continue
        days.add(_day(ts))
        e = effort[(model, eff or "—")]
        e["cost"] += cost or 0
        e["requests"] += 1
        e["output"] += out or 0
        o = sources[src or "—"]
        o["cost"] += cost or 0
        o["requests"] += 1
    total = sum(r["cost"] for r in sources.values())
    tools, decisions = defaultdict(Counter), Counter()
    for kind, ts, sid, tool, size, dec, src in telemetry["tools"]:
        first = ts if ts and (first is None or ts < first) else first
        if not inside(ts) or not keep(sid):
            continue
        days.add(_day(ts))
        if kind == "result":
            t = tools[tool]
            t["results"] += 1
            t["bytes"] += size
            t["max"] = max(t["max"], size)
        else:
            decisions[(tool, dec, src)] += 1
    return {
        "first_day": _day(first) if first else None, "days_with_events": len(days), "persistent_store": st.persistent,
        "filter": "project" if by_project else "all", "requests": sum(r["requests"] for r in sources.values()),
        "cost_usd": round(total, 4), "requests_without_session": without_meta,
        "effort": [{"model": m, "effort": e, "cost_usd": round(r["cost"], 4), "requests": int(r["requests"]),
                    "cost_per_request": round(_pct(r["cost"], r["requests"]), 4), "output_per_request": round(_pct(r["output"], r["requests"]))}
                   for (m, e), r in sorted(effort.items(), key=lambda x: -x[1]["cost"])],
        "sources": [{"query_source": s, "kind": origin_kind(s), "cost_usd": round(r["cost"], 4), "requests": int(r["requests"]),
                     "cost_share": round(_pct(r["cost"], total), 4)} for s, r in sorted(sources.items(), key=lambda x: -x[1]["cost"])],
        "tool_bytes": [{"tool": t, "results": int(r["results"]), "avg_bytes": round(_pct(r["bytes"], r["results"])), "max_bytes": int(r["max"]),
                        "total_bytes": int(r["bytes"])} for t, r in sorted(tools.items(), key=lambda x: -x[1]["bytes"]) if r["results"]],
        "decisions": [{"tool": t, "decision": d, "source": s, "count": int(n)} for (t, d, s), n in decisions.most_common()],
    }


def config_inventory(skills):
    used_cmd = {s["name"]: s["activations"] for s in skills if s["kind"] == "command"}
    used_skill = {s["name"]: s["activations"] for s in skills if s["kind"] == "skill"}
    has_cmd, has_skills = inventory.available()
    cmds = [dict(c, uses=used_cmd.get(c["name"], 0)) for c in inventory.commands()]
    sk = [dict(s, uses=used_skill.get(s["name"], 0)) for s in inventory.skills()]
    return {"commands": cmds, "skills": sk, "skills_used": sorted(used_skill),
            "note": ("Comandos de ~/.claude/commands y skills de ~/.claude/skills. No se ven los de cada proyecto ni los de plugins."
                     if has_cmd or has_skills else "No están montadas ~/.claude/commands ni ~/.claude/skills: no hay inventario.")}


# ----------------------------------------------------------------------------- detectors

def severity(f, summary):
    cost = summary["cost_usd"]
    usd = f.get("impact_usd") or 0
    if cost > 0 and usd:
        share = usd / cost
        return "alta" if share >= 0.10 else "media" if share >= 0.02 else "baja"
    if f.get("impact_tokens"):
        return "media" if f["impact_tokens"] >= 50_000_000 else "baja"
    n = f.get("impact_count") or 0
    return "alta" if n >= 100 else "media" if n >= 20 else "baja"


def _finding(detector, title, evidence, recommendation, impact_usd=None, impact_count=None, impact_tokens=None, sessions=(), subject=""):
    return {"detector": detector, "subject": subject, "title": title, "evidence": evidence, "recommendation": recommendation,
            "impact_usd": round(impact_usd, 4) if impact_usd is not None else None, "impact_count": impact_count,
            "impact_tokens": impact_tokens, "sessions": list(sessions)[:5]}


def d1_tool_errors(ctx):
    rows = defaultdict(lambda: {"errors": 0, "models": Counter(), "sessions": Counter()})
    for r in ctx["tables"]["tool_errors"]:
        if r["error_class"] in NOT_AVOIDABLE:
            continue
        g = rows[(r["tool"], r["error_class"])]
        g["errors"] += r["errors"]
        g["models"][r["model"]] += r["errors"]
        for s in r["sessions"]:
            g["sessions"][s] += 1
    calls = {t["tool"]: t["calls"] for t in ctx["tables"]["tools"]}
    out = []
    for (tool, cls), g in rows.items():
        rate = _pct(g["errors"], calls.get(tool, 0))
        if g["errors"] < 10 and not (g["errors"] >= 5 and rate >= 0.05):
            continue
        model, n = g["models"].most_common(1)[0]
        label, advice = ADVICE.get(cls, ADVICE["other"])
        conc = (" Todos con `%s`." % model) if len(g["models"]) == 1 else (
            " El %d %% de estos errores son de `%s`." % (round(100 * n / g["errors"]), model) if n / g["errors"] >= 0.6 else "")
        out.append(_finding("D1", "`%s`: %s" % (tool, label.lower()),
                            "%d errores de clase `%s` en %d llamadas a `%s` (%.1f %%).%s" % (g["errors"], cls, calls.get(tool, 0), tool, 100 * rate, conc),
                            advice, impact_usd=g["errors"] * ctx["avg_call_cost"], impact_count=g["errors"],
                            sessions=[s for s, _ in g["sessions"].most_common(5)], subject="%s/%s" % (tool, cls)))
    return out


def d2_cost_concentration(ctx):
    out = []
    # only messages whose cost is known: before the telemetry was enabled there is no cost, and counting
    # those messages would make every other model look cheap
    models = [m for m in ctx["tables"]["models"] if m["messages_with_cost"]]
    total_cost = sum(m["cost_usd"] for m in models)
    total_msgs = sum(m["messages_with_cost"] for m in models)
    for m in models:
        n = m["messages_with_cost"]
        rest_msgs = total_msgs - n
        if n < 20 or rest_msgs < 20:
            continue
        ref = (total_cost - m["cost_usd"]) / rest_msgs
        cpm = m["cost_usd"] / n
        if m["cost_share"] >= 0.4 and ref > 0 and cpm >= 2 * ref:
            out.append(_finding("D2", "El modelo `%s` concentra el coste" % m["model"],
                                "%d %% del coste conocido (%.2f $), con %.4f $ por mensaje con coste: %.1f veces el del resto de modelos juntos (%.4f $)." % (
                                    round(100 * m["cost_share"]), m["cost_usd"], cpm, cpm / ref, ref),
                                "Usa `/model` para dejar un modelo más barato por defecto y cambia a `%s` solo en las tareas que lo necesiten, "
                                "o fíjalo solo en los comandos que lo pidan (`model:` en su frontmatter)." % m["model"],
                                impact_usd=m["cost_usd"] - n * ref, subject=m["model"]))
    for a in ctx["tables"]["agents"]:
        if a["agent"] == "subagentes" and a["cost_share"] >= 0.4 and a["messages"] >= 20:
            out.append(_finding("D2", "Los subagentes concentran el coste",
                                "%d %% del coste conocido (%.2f $) en %d mensajes de subagentes. Modelos: %s." % (
                                    round(100 * a["cost_share"]), a["cost_usd"], a["messages"], ", ".join("`%s`" % x for x in a["top_models"])),
                                "Revisa cuándo se lanzan subagentes y con qué modelo; para búsquedas basta uno barato.",
                                impact_usd=a["cost_usd"] * 0.5, subject="subagentes"))
    return out


def d3_loops(ctx):
    t = ctx["tables"]["turns"]
    out = []
    if len(t["loops"]) >= 3:
        repeated = sum(x["repeated_calls"] for x in t["loops"])
        tools = Counter(x["tool"] for x in t["loops"]).most_common(3)
        out.append(_finding("D3", "Llamadas repetidas con los mismos argumentos",
                            "%d turnos repiten tres o más veces la misma llamada (%d llamadas de más). Herramientas: %s." % (
                                len(t["loops"]), repeated, ", ".join("`%s` (%d)" % x for x in tools)),
                            "Suele indicar que el agente no ve el resultado que espera y reintenta. Da la ruta o el criterio de éxito en el prompt, "
                            "o añade a CLAUDE.md: «Si una llamada no da el resultado esperado dos veces, para y explica qué ocurre».",
                            impact_usd=repeated * ctx["avg_call_cost"], impact_count=repeated, sessions=[x["session"] for x in t["loops"]], subject="loops"))
    if len(t["error_streaks"]) >= 3:
        out.append(_finding("D3", "Rachas de errores seguidos",
                            "%d turnos encadenan tres o más errores evitables seguidos (máximo %d)." % (len(t["error_streaks"]), t["error_streaks"][0]["consecutive_errors"]),
                            "El agente sigue intentándolo sin cambiar de estrategia. Suele faltar contexto (rutas, comandos de build, shell) "
                            "que se puede dejar fijo en el CLAUDE.md del proyecto.",
                            impact_count=sum(x["consecutive_errors"] for x in t["error_streaks"]), sessions=[x["session"] for x in t["error_streaks"]], subject="streaks"))
    if len(t["long_turns"]) >= 3:
        tools = Counter(x["main_tool"] for x in t["long_turns"]).most_common(3)
        out.append(_finding("D3", "Turnos con exploración muy larga",
                            "%d turnos superan %d llamadas a herramientas (mediana %d, p95 %d, máximo %d). Herramienta dominante: %s." % (
                                len(t["long_turns"]), t["long_limit"], t["p50"], t["p95"], t["max"], ", ".join("`%s` (%d)" % x for x in tools)),
                            "Delegar la búsqueda en un subagente (Explore) o indicar en el prompt los ficheros de partida reduce el contexto del hilo principal. "
                            "El impacto es el coste total de esos turnos, no lo que se ahorraría.",
                            impact_usd=sum(x["cost_usd"] for x in t["long_turns"]) or None, impact_count=len(t["long_turns"]),
                            sessions=[x["session"] for x in t["long_turns"]], subject="long_turns"))
    return out


def d4_context(ctx):
    c = ctx["tables"]["context"]
    if not c["sessions_2plus"]:
        return []
    return [_finding("D4", "Sesiones que se compactan varias veces",
                     "%d sesiones con dos o más compactaciones (máximo %d); %d compactaciones en el periodo, %d de ellas a mano con `/compact`." % (
                         len(c["sessions_2plus"]), c["sessions_2plus"][0]["compactions"], c["compactions"], c["manual"]),
                     "Cada compactación resume y pierde detalle. Parte las tareas largas en sesiones distintas (`/clear` entre tareas), "
                     "guarda el plan en un fichero y delega las búsquedas en subagentes.",
                     impact_count=c["compactions"], sessions=[x["session"] for x in c["sessions_2plus"]], subject="compactions")]


def d5_permissions(ctx):
    by_tool = defaultdict(Counter)
    sess = defaultdict(Counter)
    for c in ctx["cur"].calls:
        if c["status"] == "error" and c["cls"] in ("user_rejected", "permission_rule", "hook_blocked"):
            by_tool[c["tool"]][c["cls"]] += 1
            sess[c["tool"]][c["sid"]] += 1
    out = []
    for tool, n in by_tool.items():
        total = sum(n.values())
        if total < 3:
            continue
        out.append(_finding("D5", "`%s`: acciones bloqueadas o rechazadas" % tool,
                            "%d llamadas a `%s` no se ejecutaron (rechazadas a mano: %d; bloqueadas por regla: %d; por hook: %d)." % (
                                total, tool, n["user_rejected"], n["permission_rule"], n["hook_blocked"]),
                            "Si el agente no debería intentarlo, díselo en CLAUDE.md para que no gaste turnos; si lo rechazas porque iba mal "
                            "encaminado, da más contexto al pedir la tarea.",
                            impact_usd=total * ctx["avg_call_cost"], impact_count=total, sessions=[s for s, _ in sess[tool].most_common(5)], subject=tool))
    return out


def d6_cache(ctx):
    return [_finding("D6", "Caché casi sin uso en `%s`" % m["model"],
                     "Acierto de caché del %.0f %% con %.1f M de tokens de entrada sin caché." % (100 * m["cache_hit"], m["input_uncached"] / 1e6),
                     "Busca lo que cambia al principio del contexto en cada petición (instrucciones que se regeneran, fechas, herramientas MCP que se conectan y desconectan).",
                     impact_tokens=m["input_uncached"], subject=m["model"])
            for m in ctx["tables"]["models"] if m["input_uncached"] >= 5_000_000 and m["cache_hit"] < 0.5]


def d7_skills(ctx):
    sk = ctx["config"]["skills"]
    unused = [s["name"] for s in sk if not s["uses"]]
    if ctx["days"] < 30 or len(unused) < 2:
        return []
    return [_finding("D7", "Skills instaladas que no se usan",
                     "%d de %d skills de `~/.claude/skills` no se han cargado en %d días: %s." % (len(unused), len(sk), ctx["days"], ", ".join("`%s`" % n for n in unused)),
                     "Si deberían cargarse, revisa su `description`: es lo que Claude usa para decidir cuándo activarlas. Si no, retíralas.",
                     impact_count=len(unused), subject="unused_skills")]


def d8_pinned_models(ctx):
    health = ctx["tables"]["model_health"]
    out = []
    for c in ctx["config"]["commands"]:
        if not c["model"] or not c["uses"]:
            continue
        model = c["model"].split("/")[-1]
        h = health.get(model) or next((v for k, v in health.items() if model in k), None)
        if not h:
            continue
        problems = ["`%s` falla el %.0f %% (%d de %d)" % (t["tool"], 100 * t["rate"], t["errors"], t["calls"]) for t in h["tools"] if t["errors"] >= 5 and t["rate"] >= 0.10]
        if problems:
            out.append(_finding("D8", "El comando `%s` usa un modelo con problemas" % c["name"],
                                "Modelo fijado `%s`, usado %d veces por este comando. Con ese modelo, en el periodo: %s." % (c["model"], c["uses"], "; ".join(problems)),
                                "Cambia `model:` en `~/.claude/commands/%s.md` por un modelo más estable para lo que hace el comando." % c["name"].replace(":", "/"),
                                impact_count=c["uses"], subject=c["name"]))
    return out


def d9_aborts(ctx):
    i = ctx["tables"]["interaction"]
    if i["aborted_quick_retry"] < 5:
        return []
    return [_finding("D9", "Respuestas interrumpidas y vueltas a pedir",
                     "%d respuestas se interrumpieron y en menos de dos minutos se volvió a escribir al agente (%d interrupciones en total)." % (i["aborted_quick_retry"], i["aborted"]),
                     "Suele pasar cuando el agente arranca en mala dirección. Incluye en el primer mensaje el objetivo, los ficheros de partida "
                     "y cómo se comprueba; para tareas grandes, empieza en modo plan.",
                     impact_count=i["aborted_quick_retry"], sessions=i["aborted_quick_retry_sessions"], subject="aborts")]


def d10_commands(ctx):
    cmds = ctx["config"]["commands"]
    if not cmds:
        return []
    out = []
    names = {c["name"] for c in cmds}
    dup = sorted(c["name"] for c in cmds if c["name"].startswith("ai-") and c["name"][3:] in names)
    if dup:
        out.append(_finding("D10", "Comandos duplicados",
                            "Hay comandos con y sin el prefijo `ai-`: %s." % ", ".join("`%s` / `%s`" % (d, d[3:]) for d in dup),
                            "Quédate con una versión de cada uno para no repartir el uso ni mantener dos plantillas.",
                            impact_count=len(dup), subject="duplicates"))
    if ctx["days"] >= 30:
        unused = [c["name"] for c in cmds if not c["uses"] and c["name"] not in dup]
        if len(unused) >= 3:
            out.append(_finding("D10", "Comandos instalados que no se usan",
                                "%d de %d comandos no se han usado en %d días: %s." % (len(unused), len(cmds), ctx["days"], ", ".join("`%s`" % n for n in unused)),
                                "Retira los que ya no necesites: cada comando ocupa sitio en la lista y en el mantenimiento.",
                                impact_count=len(unused), subject="unused"))
    return out


def c1_effort(ctx):
    rows = ctx["tables"]["events"]["effort"]
    total = sum(r["cost_usd"] for r in rows)
    high = [r for r in rows if (r["effort"] or "").lower() in HIGH_EFFORT]
    low = [r for r in rows if r not in high and r["requests"]]
    hc = sum(r["cost_usd"] for r in high)
    if not total or _pct(hc, total) < 0.5:
        return []
    ref = _pct(sum(r["cost_usd"] for r in low), sum(r["requests"] for r in low))
    hreq = sum(r["requests"] for r in high)
    saved = hc - hreq * ref if ref else None
    return [_finding("C1", "La mayor parte del coste va con *effort* alto",
                     "%d %% del coste con eventos (%.2f $) usa *effort* %s, a %.4f $ por petición%s." % (
                         round(100 * hc / total), hc, "/".join(sorted({r["effort"] for r in high})), _pct(hc, hreq),
                         (" frente a %.4f $ con *effort* menor" % ref) if ref else ""),
                     "Deja un *effort* menor por defecto y súbelo solo para tareas difíciles (planificación, depuración complicada).",
                     impact_usd=saved if saved and saved > 0 else None, impact_count=hreq, subject="effort")]


def c2_background(ctx):
    rows = ctx["tables"]["events"]["sources"]
    total = sum(r["cost_usd"] for r in rows)
    bg = [r for r in rows if r["kind"] == "fondo"]
    bc = sum(r["cost_usd"] for r in bg)
    if not total or _pct(bc, total) < 0.15:
        return []
    return [_finding("C2", "Consumo de fondo apreciable",
                     "%d %% del coste con eventos (%.2f $) son llamadas de fondo: %s." % (round(100 * bc / total), bc, ", ".join("`%s` %.2f $" % (r["query_source"], r["cost_usd"]) for r in bg[:5])),
                     "Revisa las opciones que generan llamadas automáticas (sugerencias de prompt, títulos, hooks con modelo) y desactiva las que no uses.",
                     impact_usd=bc, subject="background")]


def c3_tool_bytes(ctx):
    big = [t for t in ctx["tables"]["events"]["tool_bytes"] if t["results"] >= 20 and t["avg_bytes"] >= 20000]
    if not big:
        return []
    return [_finding("C3", "Herramientas que llenan el contexto",
                     "Devuelven de media más de 20 kB por llamada: %s." % ", ".join("`%s` %d kB de media (máx. %d kB, %d llamadas)" % (
                         t["tool"], t["avg_bytes"] // 1000, t["max_bytes"] // 1000, t["results"]) for t in big[:5]),
                     "Acota la salida (limit/offset al leer, filtros en Grep, `head` o `Select-Object -First` en comandos, paginación en MCP) "
                     "o delega esas lecturas en un subagente para que no entren en el hilo principal.",
                     impact_tokens=sum(t["total_bytes"] for t in big) // 4, subject="tool_bytes")]


def c4_plans(ctx):
    i = ctx["tables"]["interaction"]
    if i["plans"] < 5 or _pct(i["plans_rejected"], i["plans"]) < 0.3:
        return []
    return [_finding("C4", "Muchos planes rechazados",
                     "%d de %d planes propuestos con `ExitPlanMode` se rechazaron (%.0f %%)." % (i["plans_rejected"], i["plans"], 100 * _pct(i["plans_rejected"], i["plans"])),
                     "Un plan rechazado es un turno perdido. Da más contexto antes de planificar (objetivo, restricciones, ficheros) o parte de una especificación (`/1-spec` antes de `/2-plan`).",
                     impact_count=i["plans_rejected"], subject="plans")]


def c5_permission_prompts(ctx):
    asked = Counter()
    for d in ctx["tables"]["events"]["decisions"]:
        if (d["decision"] or "").lower() in ("accept", "allow", "approved") and "user" in (d["source"] or "").lower():
            asked[d["tool"]] += d["count"]
    many = [(t, n) for t, n in asked.most_common() if n >= 20]
    if not many:
        return []
    return [_finding("C5", "Permisos que apruebas a mano una y otra vez",
                     "Aprobaciones manuales en el periodo: %s." % ", ".join("`%s` %d" % x for x in many[:6]),
                     "Añade reglas `allow` en `settings.json` para lo que siempre apruebas, por ejemplo `\"allow\": [%s]`, y deja la pregunta solo para lo arriesgado." % (
                         ", ".join('"%s"' % t for t, _ in many[:3])),
                     impact_count=sum(n for _t, n in many), subject="prompts")]


def c6_initial_context(ctx):
    c = ctx["tables"]["context"]
    if c["initial_context_sessions"] < 5 or c["initial_context_p50"] < 30000:
        return []
    return [_finding("C6", "Las sesiones empiezan con mucho contexto",
                     "La mediana del contexto del primer mensaje es de %d k tokens (p90 %d k) en %d sesiones, antes de que el agente haga nada." % (
                         c["initial_context_p50"] // 1000, c["initial_context_p90"] // 1000, c["initial_context_sessions"]),
                     "Ese contexto inicial son las instrucciones del sistema, los CLAUDE.md y las definiciones de herramientas MCP. Recorta los CLAUDE.md, "
                     "mueve lo que no se usa siempre a skills y desconecta los servidores MCP que no uses en cada proyecto.",
                     impact_tokens=c["initial_context_p50"] * c["initial_context_sessions"], subject="initial_context")]


DETECTORS = [d1_tool_errors, d2_cost_concentration, d3_loops, d4_context, d5_permissions, d6_cache, d7_skills, d8_pinned_models,
             d9_aborts, d10_commands, c1_effort, c2_background, c3_tool_bytes, c4_plans, c5_permission_prompts, c6_initial_context]
