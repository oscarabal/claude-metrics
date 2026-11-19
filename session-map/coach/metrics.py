"""Background work of the coach and the Prometheus series it publishes.

Everything is computed in a background thread and cached: a scrape only copies text. (In the
OpenCode module, computing these series during the scrape made it pass Prometheus' timeout.)

The thread, every round:
- saves the request costs session-map has read from Loki into the store (so they survive),
- every 10 minutes, asks Loki for the daily aggregates of the last 30 days and stores them,
- every 2 minutes, recomputes the series; every 10 minutes, the findings.
"""
import datetime
import threading
import time
from collections import Counter

from . import loki, report
from . import store as coach_store

ROUND = 30
LOKI_EVERY = 600
SERIES_EVERY = 120
FINDINGS_EVERY = 600
WEEKS = 13
WINDOWS = (7, 30, 90)

_state = {"series": [], "days": set(), "by_window": {}, "series_at": 0, "findings_at": 0, "loki_at": 0, "loki_errors": []}
_lock = threading.Lock()


def _day(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


def _week(ms):
    d = datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).date()
    return (d - datetime.timedelta(days=d.weekday())).isoformat()


def _esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _lab(**kw):
    return ",".join('%s="%s"' % (k, _esc(v)) for k, v in kw.items())


def start(ix):
    st = coach_store.get()
    try:
        st.restore(ix)  # costs from earlier runs, before the index starts reading Loki again
    except Exception:
        pass
    threading.Thread(target=_loop, args=(ix,), daemon=True).start()


def _loop(ix):
    while True:
        try:
            _round(ix)
        except Exception:  # the next round retries; scrapes keep serving the cache
            pass
        time.sleep(ROUND)


def _round(ix):
    st = coach_store.get()
    st.save_requests(ix)
    now = time.time()
    if now - _state["loki_at"] >= LOKI_EVERY:
        rows, errors = loki.daily_aggregates(30)
        st.put_daily(rows)
        with _lock:
            _state.update(loki_at=now, loki_errors=errors)
    if not ix.done:
        return
    series_due = now - _state["series_at"] >= SERIES_EVERY
    findings_due = now - _state["findings_at"] >= FINDINGS_EVERY
    if not (series_due or findings_due):
        return
    data = report.snapshot(ix)  # one copy of the index for both
    if series_due:
        series, days = _series(data, st)
        with _lock:
            _state.update(series=series, days=days, series_at=time.time())
    if findings_due:
        ms = int(time.time() * 1000)
        by_window = {}
        for w in WINDOWS:
            r = report.build(ix, ms - w * 86400000, ms, "w%d" % w, data=data)
            by_window[w] = [(f["detector"], f["severity"], f.get("impact_usd") or 0.0) for f in r["findings"]]
        with _lock:
            _state.update(by_window=by_window, findings_at=time.time())


def _series(data, st):
    sessions, costs = data
    out, days = [], set()
    add = out.append
    week_from = (time.time() - WEEKS * 7 * 86400) * 1000
    calls_d, errs_d, comp_d, intr_d = Counter(), Counter(), Counter(), Counter()
    calls_w, errs_w, cost_w, msgs_w = Counter(), Counter(), Counter(), Counter()
    for s in sessions:
        proj = s["project"]
        for c in s["calls"]:
            if not c[0] or not c[5]:
                continue
            d = _day(c[0])
            days.add(d)
            calls_d[(d, c[1], c[2], proj)] += 1
            if c[5] == "error":
                errs_d[(d, c[1], c[6] or "other", c[2], proj)] += 1
            if c[0] >= week_from:
                w = _week(c[0])
                calls_w[(w, c[1], proj)] += 1
                if c[5] == "error":
                    errs_w[(w, c[1], c[6] or "other", proj)] += 1
        for comp in s["compactions"]:
            if comp[0]:
                comp_d[(_day(comp[0]), proj)] += 1
        for ts, _turn in s["interrupts"]:
            if ts:
                intr_d[(_day(ts), proj)] += 1
        for m in s["msgs"]:
            if m[0] >= week_from and m[2] + m[3] + m[4] + m[5] > 0:
                w = _week(m[0])
                cost_w[(w, m[1], proj)] += costs.get(m[7], 0) if m[7] else 0
                msgs_w[(w, m[1], proj)] += 1
    for name, data_, keys in (
            ("claude_coach_day_tool_calls", calls_d, ("day", "tool", "model", "project")),
            ("claude_coach_day_tool_errors", errs_d, ("day", "tool", "error_class", "model", "project")),
            ("claude_coach_day_compactions", comp_d, ("day", "project")),
            ("claude_coach_day_interrupts", intr_d, ("day", "project")),
            ("claude_coach_week_tool_calls", calls_w, ("week", "tool", "project")),
            ("claude_coach_week_tool_errors", errs_w, ("week", "tool", "error_class", "project")),
            ("claude_coach_week_cost_usd", cost_w, ("week", "model", "project")),
            ("claude_coach_week_messages", msgs_w, ("week", "model", "project"))):
        add("# TYPE %s gauge" % name)
        for k, v in data_.items():
            add("%s{%s} %s" % (name, _lab(**dict(zip(keys, k))), round(v, 6)))
    days.update(d for d, _p in comp_d)
    days.update(d for d, _p in intr_d)
    # Loki aggregates kept in the store: effort and bytes returned by tools, per day
    first = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 400 * 86400))
    last = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 86400))
    effort = Counter()
    for d, model, eff, _src, v in st.daily("cost", first, last):
        effort[(d, model, eff or "—")] += v
    add("# TYPE claude_coach_day_effort_cost_usd gauge")
    for (d, model, eff), v in effort.items():
        days.add(d)
        add("claude_coach_day_effort_cost_usd{%s} %s" % (_lab(day=d, model=model, effort=eff), round(v, 6)))
    for kind, name in (("tool_results", "claude_coach_day_tool_results"), ("tool_bytes", "claude_coach_day_tool_bytes")):
        add("# TYPE %s gauge" % name)
        for d, tool, _b, _c, v in st.daily(kind, first, last):
            days.add(d)
            add("%s{%s} %s" % (name, _lab(day=d, tool=tool), v))
    return out, days


def lines():
    """What a scrape publishes; reads nothing but the cache."""
    with _lock:
        out = list(_state["series"])
        by_window = dict(_state["by_window"])
        f_at, s_at, errors = _state["findings_at"], _state["series_at"], list(_state["loki_errors"])
    add = out.append
    add("# TYPE claude_coach_findings gauge")
    add("# TYPE claude_coach_finding_impact_usd gauge")
    for w, items in by_window.items():
        count, impact = Counter(), Counter()
        for det, sev, usd in items:
            count[(det, sev)] += 1
            impact[det] += usd
        for (det, sev), n in count.items():
            add("claude_coach_findings{%s} %d" % (_lab(window=w, detector=det, rule=report.RULES.get(det, det), severity=sev), n))
        for det, v in impact.items():
            add("claude_coach_finding_impact_usd{%s} %s" % (_lab(window=w, detector=det, rule=report.RULES.get(det, det)), round(v, 4)))
    add("# TYPE claude_coach_findings_updated_timestamp_seconds gauge")
    add("claude_coach_findings_updated_timestamp_seconds %d" % f_at)
    add("# TYPE claude_coach_series_updated_timestamp_seconds gauge")
    add("claude_coach_series_updated_timestamp_seconds %d" % s_at)
    add("# TYPE claude_coach_store_persistent gauge")
    add("claude_coach_store_persistent %d" % (1 if coach_store.get().persistent else 0))
    add("# TYPE claude_coach_loki_errors gauge")
    add("claude_coach_loki_errors %d" % len(errors))
    return out


def days():
    with _lock:
        return set(_state["days"])
