"""Command line: write the improvement report to standard output.

It reads the conversation files itself (it does not share the running server's memory), so it
takes as long as session-map's first scan. The store gives it the costs and the Loki aggregates.

    docker compose exec session-map python /app/coach/cli.py report --window 30 > informe.md
"""
import argparse
import calendar
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import index  # noqa: E402
from coach import render, report  # noqa: E402
from coach import store as coach_store  # noqa: E402


def day_ms(text, end=False):
    t = calendar.timegm(time.strptime(text, "%Y-%m-%d")) * 1000
    return t + 86399999 if end else t


def main(argv=None):
    ap = argparse.ArgumentParser(prog="coach")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", help="informe de mejoras")
    r.add_argument("--window", type=int, default=30, help="días hacia atrás (0 = todo el historial)")
    r.add_argument("--from", dest="date_from", help="día inicial AAAA-MM-DD (UTC)")
    r.add_argument("--to", dest="date_to", help="día final AAAA-MM-DD (UTC)")
    r.add_argument("--project", action="append")
    r.add_argument("--anon", action="store_true")
    r.add_argument("--format", choices=("md", "json"), default="md")
    pr = sub.add_parser("probe", help="muestra el principio enmascarado de los errores de unas clases, para ajustar el clasificador")
    pr.add_argument("--classes", default="other,hook_blocked,timeout,command_failed")
    pr.add_argument("--top", type=int, default=25)
    args = ap.parse_args(argv)
    if args.cmd == "probe":
        return probe(set(args.classes.split(",")), args.top)

    now = int(time.time() * 1000)
    if args.date_from or args.date_to:
        since = day_ms(args.date_from) if args.date_from else 0
        until = day_ms(args.date_to, end=True) if args.date_to else now
        label = "del %s al %s" % (args.date_from or "inicio", args.date_to or "hoy")
    elif args.window > 0:
        since, until, label = now - args.window * 86400000, now, "últimos %d días" % args.window
    else:
        since, until, label = 0, now, "todo el historial"

    ix = index.INDEX
    coach_store.get().restore(ix)
    try:
        ix.scan_costs()
    except Exception:
        pass
    ix.scan_files()
    data = report.build(ix, since, until, label, set(args.project) if args.project else None, args.anon)
    out = render.render(data) if args.format == "md" else render.render_json(data)
    sys.stdout.buffer.write(out.encode("utf-8"))


def probe(classes, top):
    """Group the tool errors of some classes by the start of their text, with paths, numbers and ids masked."""
    import json
    import re
    from collections import Counter
    from coach import errors
    mask = lambda t: re.sub(r"\d+", "N", re.sub(r"[A-Za-z]:[\\/][^\s'\"<>]+|/[\w.\-/]+|[0-9a-f]{8}-[0-9a-f-]{27,}", "<path>", t))[:90]
    groups = {c: Counter() for c in classes}
    for folder, _dirs, names in os.walk(index.ROOT):
        for n in names:
            if not n.endswith(".jsonl"):
                continue
            tools = {}
            try:
                lines = open(os.path.join(folder, n), encoding="utf-8", errors="replace").read().splitlines()
            except OSError:
                continue
            for line in lines:
                if '"tool_use"' in line or '"is_error":true' in line:
                    try:
                        j = json.loads(line)
                    except ValueError:
                        continue
                    for b in (j.get("message") or {}).get("content") or []:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "tool_use":
                            tools[b.get("id")] = b.get("name")
                        elif b.get("type") == "tool_result" and b.get("is_error"):
                            text = index._text_of(b.get("content"))
                            tool = tools.get(b.get("tool_use_id"), "?")
                            cls = errors.classify(text, tool)
                            if cls in groups:
                                groups[cls][(tool, mask(" ".join(text.split())))] += 1
    for cls, c in groups.items():
        print("== %s (%d)" % (cls, sum(c.values())))
        for (tool, text), k in c.most_common(top):
            print("%4d  %-28s %s" % (k, tool[:28], text))


if __name__ == "__main__":
    main()
