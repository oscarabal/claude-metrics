"""Daily aggregates of the Claude Code events kept in Loki.

Only metric queries are made (sums and counts per day), never a list of events, so no text comes
back. They run in session-map's background thread and the results go to the store.
"""
import json
import os
import time
import urllib.parse
import urllib.request

LOKI_URL = os.environ.get("LOKI_URL", "http://loki:3100")
SEL = '{service_name=~".+"}'

# kind -> LogQL over one day; the labels it is grouped by become a, b, c in the store
QUERIES = {
    "cost": ('sum by (model, effort, query_source) (sum_over_time(%s | event_name="api_request" | unwrap cost_usd | __error__="" [1d]))',
             ("model", "effort", "query_source")),
    "requests": ('sum by (model, effort, query_source) (count_over_time(%s | event_name="api_request" [1d]))',
                 ("model", "effort", "query_source")),
    "output_tokens": ('sum by (model, effort, query_source) (sum_over_time(%s | event_name="api_request" | unwrap output_tokens | __error__="" [1d]))',
                      ("model", "effort", "query_source")),
    "tool_results": ('sum by (tool_name) (count_over_time(%s | event_name="tool_result" [1d]))', ("tool_name",)),
    "tool_bytes": ('sum by (tool_name) (sum_over_time(%s | event_name="tool_result" | unwrap tool_result_size_bytes | __error__="" [1d]))', ("tool_name",)),
    "tool_bytes_max": ('max by (tool_name) (max_over_time(%s | event_name="tool_result" | unwrap tool_result_size_bytes | __error__="" [1d]))', ("tool_name",)),
    "decisions": ('sum by (tool_name, decision, source) (count_over_time(%s | event_name="tool_decision" [1d]))', ("tool_name", "decision", "source")),
}


def _query_range(query, start, end):
    url = LOKI_URL + "/loki/api/v1/query_range?" + urllib.parse.urlencode(
        {"query": query, "start": start, "end": end, "step": "86400s"})
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)["data"]["result"]


def daily_aggregates(days=30, now=None):
    """Rows (day, kind, a, b, c, value) for the last `days` complete and current UTC days."""
    now = int(now or time.time())
    end = (now // 86400 + 1) * 86400          # next midnight: the last point covers today so far
    start = end - days * 86400
    rows, errors = [], []
    for kind, (template, labels) in QUERIES.items():
        try:
            series = _query_range(template % SEL, start, end)
        except Exception as e:  # a failed query leaves that kind for the next round
            errors.append("%s: %s" % (kind, e))
            continue
        for s in series:
            metric = s.get("metric", {})
            keys = [metric.get(l, "") for l in labels] + [""] * (3 - len(labels))
            for ts, value in s.get("values", []):
                # a point at midnight sums the day that has just ended
                day = time.strftime("%Y-%m-%d", time.gmtime(int(float(ts)) - 86400))
                try:
                    rows.append((day, kind, keys[0], keys[1], keys[2], float(value)))
                except ValueError:
                    pass
    return rows, errors
