"""SEB-470: the browser bundle drops rows older than 365 days and keeps recent ones. Fixture rows only."""
import datetime as dt
import os
import sys

import duckdb

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import emit_bundle  # noqa: E402

assert emit_bundle.BUNDLE_HISTORY_DAYS == 365

now = dt.datetime(2026, 11, 19, 12, 0, tzinfo=dt.timezone.utc)
old = (now - dt.timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")
new = (now - dt.timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")

con = duckdb.connect()
con.execute("CREATE TABLE timed (ts VARCHAR, v INTEGER)")
con.execute("INSERT INTO timed VALUES (?, 1), (?, 2), (NULL, 3)", [old, new])
con.execute("CREATE TABLE untimed (name VARCHAR, v INTEGER)")
con.execute("INSERT INTO untimed VALUES ('a', 1), ('b', 2)")

dropped = emit_bundle.trim_history(con, ["timed", "untimed"], now=now)
assert dropped == {"timed": 1}, dropped
kept = [r[0] for r in con.execute("SELECT v FROM timed ORDER BY v").fetchall()]
assert kept == [2, 3], kept
assert con.execute("SELECT count(*) FROM untimed").fetchone()[0] == 2
print("bundle cutoff: ok")
