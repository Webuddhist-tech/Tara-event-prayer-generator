#!/usr/bin/env python3
"""Export one IST day's prayer requests from Postgres to input/<YYYY-MM-DD>.json.

usage: python scripts/export_prayers.py [--date YYYY-MM-DD]      (default: yesterday in Asia/Kolkata)
env:   DATABASE_URL   postgres://user:pass@host:5432/dbname?sslmode=require   (read-only user recommended)

Writes the same shape as the manual export: { "<sql>": [ {message_id, message, created_at, posted_by,
username, email, id, prayed_count}, ... ] } and prints the date and row count.
Profile photos are not selected here; fetch_avatars.py loads them from Auth0 by email.
Also writes the date to $GITHUB_OUTPUT (date=..., count=...) when run inside GitHub Actions.
"""
import argparse, datetime, json, os, sys
from zoneinfo import ZoneInfo
import psycopg

IST = ZoneInfo('Asia/Kolkata')

# One IST calendar day: from 00:00 IST inclusive to the next 00:00 IST exclusive.
# A run on 25 Sept (IST) with no --date exports 24 Sept.
SQL = """
SELECT m.id AS message_id, m.body AS message, m.created_at,
       trim(concat(u.firstname,' ',coalesce(u.lastname,''))) AS posted_by,
       u.username, u.email, u.id, count(p.id) AS prayed_count
FROM public.chat_messages m
JOIN public.users u ON u.id = m.sender_id
LEFT JOIN public.chat_message_prayers p ON p.message_id = m.id
WHERE m.message_type = 'PRAYER' AND m.deleted_at IS NULL
  AND m.created_at >= %(start)s
  AND m.created_at < %(end)s
GROUP BY m.id, m.body, m.created_at, u.firstname, u.lastname, u.username, u.email, u.id
ORDER BY m.created_at
"""

ap = argparse.ArgumentParser()
ap.add_argument('--date', help='YYYY-MM-DD (IST). Default: yesterday in Asia/Kolkata')
ap.add_argument('--outdir', default='input')
A = ap.parse_args()

day = (datetime.date.fromisoformat(A.date) if A.date
       else datetime.datetime.now(IST).date() - datetime.timedelta(days=1))
start = datetime.datetime.combine(day, datetime.time.min, tzinfo=IST)
end = start + datetime.timedelta(days=1)

url = os.environ.get('DATABASE_URL')
if not url:
    sys.exit('DATABASE_URL is not set (add it as a repository secret).')


def jsonable(v):
    if isinstance(v, datetime.datetime):
        if v.tzinfo is None:                       # timestamp without time zone = stored as UTC
            v = v.replace(tzinfo=datetime.timezone.utc)
        return v.astimezone(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    if isinstance(v, (int, float, str)) or v is None:
        return v
    return str(v)                                  # uuid, Decimal, ...


with psycopg.connect(url, connect_timeout=20) as conn, conn.cursor() as cur:
    cur.execute(SQL, {'start': start, 'end': end})
    cols = [c.name for c in cur.description]
    rows = [{k: jsonable(v) for k, v in zip(cols, r)} for r in cur.fetchall()]

os.makedirs(A.outdir, exist_ok=True)
path = os.path.join(A.outdir, f'{day.isoformat()}.json')
json.dump({SQL.strip(): rows}, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f'{day.isoformat()}: {len(rows)} prayer requests -> {path}')

gh = os.environ.get('GITHUB_OUTPUT')
if gh:
    with open(gh, 'a') as f:
        f.write(f'date={day.isoformat()}\ncount={len(rows)}\njson={path}\n')
