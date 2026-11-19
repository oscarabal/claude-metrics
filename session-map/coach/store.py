"""Small SQLite store so the history does not depend on Loki's 30 days or on a restart.

It keeps only metadata: each request (cost, model, query source, effort, session and output tokens), each
tool event (tool, session, bytes returned, permission decision) and daily aggregates of the Loki events for
the Grafana series. Never any text, nor the tool parameters. If the volume is missing it falls back to memory.
"""
import os
import sqlite3
import threading

DB_PATH = os.environ.get("COACH_DB", "/state/coach.db")

SCHEMA = """
create table if not exists request_cost (
    request_id text primary key, prompt_id text, model text, origin text, cost real, ts integer);
create table if not exists tool_event (
    tool_use_id text, kind text, ts integer, session_id text, tool text, bytes integer, decision text, source text,
    primary key (tool_use_id, kind));
create table if not exists daily (
    day text, kind text, a text, b text, c text, value real,
    primary key (day, kind, a, b, c));
"""


class Store:
    def __init__(self, path=DB_PATH):
        self.lock = threading.Lock()
        self.persistent = True
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self.conn = sqlite3.connect(path, check_same_thread=False)
            self.conn.executescript(SCHEMA)
        except (OSError, sqlite3.Error):
            self.persistent = False
            self.conn = sqlite3.connect(":memory:", check_same_thread=False)
            self.conn.executescript(SCHEMA)
        cols = {r[1] for r in self.conn.execute("pragma table_info(request_cost)")}
        for col, kind in (("session_id", "text"), ("effort", "text"), ("output_tokens", "integer")):
            if col not in cols:  # stores created before these columns existed
                self.conn.execute("alter table request_cost add column %s %s" % (col, kind))
        self.conn.commit()
        self.saved = set()
        self.need_meta = set()   # stored requests still without session and effort
        self.saved_tools = set()

    # ---------------------------------------------------------------- request costs
    def restore(self, ix):
        """Put the stored request costs back into the index, so old sessions keep their cost after a restart."""
        with self.lock:
            rows = self.conn.execute("select request_id, prompt_id, model, origin, cost, ts, session_id, effort, output_tokens "
                                     "from request_cost").fetchall()
            tools = self.conn.execute("select tool_use_id, kind, ts, session_id, tool, bytes, decision, source from tool_event").fetchall()
        with ix.lock:
            for rid, pid, model, origin, cost, ts, sid, effort, out in rows:
                ix.costs.setdefault(rid, cost)
                ix.requests.setdefault(rid, (pid or "", model or "unknown", origin or "unknown", cost))
                if ts:
                    ix.request_ts.setdefault(rid, ts)
                if sid is None:
                    self.need_meta.add(rid)
                else:
                    ix.request_meta.setdefault(rid, (sid, effort or "", out or 0))
                self.saved.add(rid)
            for tid, kind, ts, sid, tool, size, dec, src in tools:
                ix.tool_events.setdefault((tid, kind), (ts, sid, tool, size, dec, src))
                self.saved_tools.add((tid, kind))
        return len(rows)

    def save_requests(self, ix):
        with ix.lock:
            new = [(rid, req, ix.request_ts.get(rid), ix.request_meta.get(rid)) for rid, req in ix.requests.items() if rid not in self.saved]
            late = [(rid, ix.request_meta[rid]) for rid in self.need_meta if rid in ix.request_meta]
            tools = [(k, v) for k, v in ix.tool_events.items() if k not in self.saved_tools]
        if not (new or late or tools):
            return 0
        with self.lock:
            self.conn.executemany(
                "insert or ignore into request_cost (request_id, prompt_id, model, origin, cost, ts, session_id, effort, output_tokens) "
                "values (?,?,?,?,?,?,?,?,?)",
                [(rid, pid, model, origin, cost, ts) + (tuple(meta) if meta else (None, None, None))
                 for rid, (pid, model, origin, cost), ts, meta in new])
            self.conn.executemany("update request_cost set session_id = ?, effort = ?, output_tokens = ? where request_id = ?",
                                  [(sid, eff, out, rid) for rid, (sid, eff, out) in late])
            self.conn.executemany("insert or replace into tool_event values (?,?,?,?,?,?,?,?)",
                                  [(tid, kind) + tuple(v) for (tid, kind), v in tools])
            self.conn.commit()
        self.saved.update(rid for rid, _req, _ts, meta in new)
        self.need_meta.update(rid for rid, _req, _ts, meta in new if not meta)
        self.need_meta.difference_update(rid for rid, _m in late)
        self.saved_tools.update(k for k, _v in tools)
        return len(new) + len(late) + len(tools)

    # ---------------------------------------------------------------- daily aggregates
    def put_daily(self, rows):
        """rows: (day, kind, a, b, c, value); a day already stored is replaced, since Loki gives its full total."""
        if not rows:
            return
        with self.lock:
            self.conn.executemany("insert or replace into daily values (?,?,?,?,?,?)", rows)
            self.conn.commit()

    def daily(self, kind, first_day, last_day):
        with self.lock:
            return self.conn.execute(
                "select day, a, b, c, value from daily where kind = ? and day between ? and ?", (kind, first_day, last_day)).fetchall()

    def first_day(self):
        with self.lock:
            row = self.conn.execute("select min(day) from daily").fetchone()
        return row[0] if row else None


STORE = None


def get():
    global STORE
    if STORE is None:
        STORE = Store()
    return STORE
