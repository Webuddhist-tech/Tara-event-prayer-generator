# Daily prayer-request PDF (Zabtik Drolchok)

Every morning at **07:00 IST** a GitHub Action builds the A3 "Prayer Requests" PDF for the
**previous day (IST)** and publishes it as a GitHub Release named `prayers-YYYY-MM-DD`
(the PDF is also attached to the Actions run as an artifact, kept 90 days).

```
Postgres ──export_prayers.py──▶ input/<date>.json
Auth0    ──fetch_avatars.py───▶ avatars.json + profile_images/
                build_prayer_pdf.py (Chromium, 5-column A3 cards) ──▶ output/Prayer_Requests_<date>_A3.pdf ──▶ Release
```

## One-time setup

1. **Create a PRIVATE GitHub repo** and push this folder to it. It must stay private: `fonts/` holds
   Garamond (Microsoft) and Monlam Uni OuChan2, which must not be published.
2. **Add repository secrets** (Settings → Secrets and variables → Actions → New repository secret):

   | Secret | Value |
   |---|---|
   | `DATABASE_URL` | `postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require` – ideally a read-only user with SELECT on `chat_messages`, `chat_message_prayers`, `users` |
   | `AUTH0_DOMAIN` | `we-buddhist-prod.us.auth0.com` |
   | `AUTH0_CLIENT_ID` | client ID of a Machine-to-Machine app authorised for the **Auth0 Management API** |
   | `AUTH0_CLIENT_SECRET` | that app's client secret |

   The M2M app needs only the `read:users` permission. The Action requests a fresh token on every
   run, so nothing expires. **Rotate any client secret that was ever pasted into a chat or doc.**
   If the Auth0 secrets are missing or wrong, the PDF is still built – everyone gets initials.
3. **Test it now:** Actions tab → *Daily prayer-request PDF* → **Run workflow** (optionally type a
   date such as `2026-09-26`). The first run also tells you whether GitHub can reach the database.

## Daily use

Open the repo's **Releases** page each morning and download `Prayer_Requests_<date>_A3.pdf`.
Print on A3 at 100% / Actual size. To rebuild a day, run the workflow manually with that date –
the PDF in that day's Release is replaced.

## Notes

- Schedule: cron `30 1 * * *` (UTC). GitHub can start scheduled runs a few minutes late, and it
  pauses schedules in repos with no activity for 60 days – any push or manual run re-enables it.
- Cleanup rules (in `build_prayer_pdf.py`): drops "no sound la"/"no video la" and emoji-only messages;
  strips emojis and WeChat codes like `[合十]`/`[Worship]`; tidies names. The run log prints everything dropped.
- De-duplication (per day, per person): messages are grouped by the user's **id** (not display name, which
  collides e.g. "WeBuddhist Member"), compared after removing emojis/punctuation/spaces and NFKC-normalising,
  and merged when identical or at least 90% similar (texts long enough to judge – about 20 Latin or 10 Chinese/Tibetan characters – so short mantras are only merged when identical). The fuller version is kept in
  the first one's position; on a tie the first wins. Different people are never merged, and the same prayer
  on a different day is kept (each day is offered separately). Nothing is deleted from the database.
- If the database only allows known IPs, GitHub-hosted runners won't connect; use a self-hosted
  runner (change `runs-on`) or allow-list GitHub's IP ranges.
