"""Small SQLite store so the history does not depend on Loki's 30 days or on a restart.

It keeps only metadata: the cost of each request (as session-map reads it from Loki) and daily
aggregates of the Loki events the report uses (effort, query source, bytes returned by tools,
permission decisions). Never any text. If the volume is missing it falls back to memory.
"""
import os
import sqlite3
import threading

DB_PATH = os.environ.get("COACH_DB", "/state/coach.db")

SCHEMA = """
create table if not exists request_cost (
    request_id text primary key, prompt_id text, model text, origin text, cost real, ts integer);
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
        self.saved = set()

    # ---------------------------------------------------------------- request costs
    def restore(self, ix):
        """Put the stored request costs back into the index, so old sessions keep their cost after a restart."""
        with self.lock:
            rows = self.conn.execute("select request_id, prompt_id, model, origin, cost, ts from request_cost").fetchall()
        with ix.lock:
            for rid, pid, model, origin, cost, ts in rows:
                ix.costs.setdefault(rid, cost)
                ix.requests.setdefault(rid, (pid or "", model or "unknown", origin or "unknown", cost))
                if ts:
                    ix.request_ts.setdefault(rid, ts)
                self.saved.add(rid)
        return len(rows)

    def save_requests(self, ix):
        with ix.lock:
            new = [(rid, req, ix.request_ts.get(rid)) for rid, req in ix.requests.items() if rid not in self.saved]
        if not new:
            return 0
        with self.lock:
            self.conn.executemany(
                "insert or ignore into request_cost values (?,?,?,?,?,?)",
                [(rid, pid, model, origin, cost, ts) for rid, (pid, model, origin, cost), ts in new])
            self.conn.commit()
        self.saved.update(rid for rid, _req, _ts in new)
        return len(new)

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
