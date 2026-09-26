#!/usr/bin/env python3
"""Print each finished IST day that has prayer requests, oldest first.

A day is finished when it is before today in Asia/Kolkata. Today is left out
because that calendar day is still open. One date per line: YYYY-MM-DD.
"""
import datetime
import os
import sys
from zoneinfo import ZoneInfo

import psycopg

IST = ZoneInfo("Asia/Kolkata")

SQL = """
SELECT DISTINCT (m.created_at AT TIME ZONE 'Asia/Kolkata')::date AS day
FROM public.chat_messages m
WHERE m.message_type = 'PRAYER'
  AND m.deleted_at IS NULL
  AND m.created_at < %(today)s
ORDER BY day
"""


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set (add it as a repository secret).")
    today = datetime.datetime.combine(
        datetime.datetime.now(IST).date(), datetime.time.min, tzinfo=IST
    )
    with psycopg.connect(url, connect_timeout=20) as conn, conn.cursor() as cur:
        cur.execute(SQL, {"today": today})
        for (day,) in cur.fetchall():
            print(day.isoformat())


if __name__ == "__main__":
    main()
