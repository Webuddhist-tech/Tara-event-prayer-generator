# Daily Prayer List for the Lama – Project Gist

## Goal
Turn each day's prayer requests from the WeBuddhist app into a beautiful, printable
PDF (A3, card grid) that is presented to a Lama, showing each person's name,
avatar and prayer message.

## Data source
PostgreSQL export (JSON) of prayer messages for one day (Asia/Kolkata date):

```sql
SELECT m.id AS message_id, m.body AS message, m.created_at,
       trim(concat(u.firstname,' ',coalesce(u.lastname,''))) AS posted_by,
       u.username, u.email, u.image, count(p.id) AS prayed_count
FROM public.chat_messages m
JOIN public.users u ON u.id = m.sender_id
LEFT JOIN public.chat_message_prayers p ON p.message_id = m.id
WHERE m.message_type = 'PRAYER' AND m.deleted_at IS NULL
  AND (m.created_at AT TIME ZONE 'Asia/Kolkata')::date = DATE '<YYYY-MM-DD>'
GROUP BY m.id, m.body, m.created_at, u.firstname, u.lastname, u.username, u.email, u.image
ORDER BY m.created_at;
```

Messages are multilingual: English, Tibetan, Chinese (Simplified + Traditional), Vietnamese.

## Output design
- A3 portrait PDF, 3-column masonry card grid (short cards pack tightly, very long prayers flow across columns)
- Header: Tibetan "སྨོན་ལམ།", "PRAYER REQUESTS", "Respectfully offered for the Lama's prayers and blessings", date + count
- Each card: round avatar + name + "No. XX", then the message
- Footer blessing: "སེམས་ཅན་ཐམས་ཅད་བདེ་བ་དང་ལྡན་པར་གྱུར་ཅིག" / "May all beings have happiness and the causes of happiness."
- Palette: maroon #7a1f1f, gold #b8872b, cream card #fdf8ee
- Fonts: Garamond (Latin), Monlam Uni OuChan2 (Tibetan), Noto Serif CJK (Chinese)
- Rendered as HTML → PDF with headless Chromium (needed for correct Tibetan stacking)

## Cleanup rules
- Drop non-prayer messages (e.g. "no sound la", "no video la" – app feedback)
- "Webuddhist _user_123" → "WeBuddhist Member"; strip "_user_123" suffixes from other names
- Title-case ALL-CAPS / lowercase Latin names; collapse repeated names ("cathy cathy" → "Cathy")
- Chinese names shown surname-first (e.g. "旭艺 沈" → "沈旭艺")
- Remove emojis and "[合十]"; keep the wording otherwise unchanged

## Avatars
Auth0 is the single source of profile photos. The `users.avatar_url` / S3 key in the
export is deliberately ignored.

- `fetch_avatars.py` looks every person with an email up in the Management API in bulk
  (`GET /api/v2/users?q=email:(...)&search_engine=v3`, 25 emails per request) and
  downloads their `picture` into `profile_images/`.
- Token: read from `env.txt` (the `Bearer ...` in the curl line) or `AUTH0_TOKEN`.
  It needs audience `https://we-buddhist-prod.us.auth0.com/api/v2/` **and** the
  `read:users` scope. Scopes are baked in at issue time, so after granting a
  permission you must re-issue the token - an existing one never picks it up.
  The script checks the `scope` claim locally and refuses to start without it.
- Two kinds of fake photo are rejected so the person keeps the house-style initials
  circle:
  1. Auth0/Gravatar default avatars, detectable from the url
     (`cdn.auth0.com/avatars`).
  2. Google auto-generated letter avatars, which come from the *same*
     `lh3.googleusercontent.com/a/ACg8oc...` urls as real photos and can only be told
     apart by their pixels: a flat colour block with one glyph. `is_letter_avatar()`
     rejects an image with fewer than 400 distinct colours where one colour covers
     over 80% of it. Real photos in this data start near 1600 colours and the letter
     avatars top out near 170, so the gap is wide.
- Everyone else gets a coloured initials circle (colour fixed per name; Chinese =
  surname character, Tibetan = first syllable, placeholder accounts = "WB").

`avatars.json` - one entry per email:
```json
"terlar@gmail.com": {
  "source": "auth0",
  "avatar_url": "https://lh3.googleusercontent.com/a/...",
  "file": "profile_images/terlar_gmail_com.jpg",
  "downloaded": true,
  "name": "Terje Larsen",
  "user_id": "...",
  "avatar": "photo"          // or "initials", with "placeholder": true
}
```

## Security notes
- Never paste client secrets or access tokens into chats/docs; keep them in env vars.
- Rotate any secret that has been shared.

## Automation (GitHub Actions)
Repo: `Webuddhist-tech/Tara-event-prayer-generator`. Workflow
`.github/workflows/daily-prayer-pdf.yml` runs 01:30 UTC = 07:00 IST daily, and can be
run by hand with an optional date. It exports the day from the database, fetches
avatars, builds the A3 PDF, uploads it as an artifact and publishes it as a Release
tagged `prayers-<date>`.

- The job runs with `working-directory: prayer-pdf-action`, because the scripts,
  fonts and requirements live in that folder rather than at the repo root.
  `upload-artifact` is not a `run` step, so its path is spelled in full.
- Repo secrets needed: `DATABASE_URL`, `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`,
  `AUTH0_CLIENT_SECRET`.
- No token is stored anywhere. `scripts/fetch_avatars.py` mints a fresh Management API
  token from the client credentials on every run, so nothing expires. Photos are
  re-downloaded every run, so a profile picture changed in the app appears on the next
  day's PDF by itself.
- If Auth0 is unreachable or misconfigured the job does not fail: it writes an empty
  avatars.json, prints a `::warning::` on the run summary, and the PDF is built with
  everyone on initials.
- `env.txt` is git-ignored. It only matters for running the scripts by hand.

## Status
- Done: A4 list PDF, A3 card PDF, A3 card PDFs with real photos (25 + 26 Sept)
- Done: Auth0 pipeline, covering both day files. `avatars.json` holds 116 people,
  26 with a real photo in `profile_images/`; everyone else gets an initials circle
  (90 of them are Auth0/Gravatar defaults or Google letter avatars, not misses).
- Done: `fetch_avatars.py` in the project root (manual runs) takes day files as
  arguments, `--all` for every file in `input_file/`, and prefers
  `AUTH0_CLIENT_ID`/`AUTH0_CLIENT_SECRET` (minting a fresh token) over a pasted
  24 h token in `env.txt`.
- Done: CI script now treats a 401 like a 403 and checks the minted token for the
  `read:users` scope up front, instead of silently producing an initials-only PDF.
- Next: set the four repo secrets, commit, and trigger the workflow once by hand to
  confirm a Release appears.
