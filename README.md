# WebUntis -> Apple Calendar sync

1. `export WEBUNTIS_USER=... WEBUNTIS_PASSWORD=...` (or `WEBUNTIS_COOKIE` if your school uses SSO)
2. `python3 webuntis_sync.py` -> writes `out/schedule.ics`, `out/schedule.md`, `out/snapshots/<date>.json`, `out/CHANGES.md`
3. `./remove_maker_lab.sh` (dry run), then `./remove_maker_lab.sh --delete`
4. Open `out/schedule.ics` -> Calendar asks which calendar to add to (use a dedicated one, e.g. "Berufsschule").

Re-run any time: event UIDs are stable, so re-importing updates existing events (cancelled lessons
are marked `ENTFALL:` / STATUS:CANCELLED) instead of duplicating them. `CHANGES.md` lists what moved
since the last snapshot — paste it into GitHub issues.

Automatic updates: commit this folder to a repo and run the script from a scheduled GitHub Action
(credentials as repo secrets), then subscribe Calendar to the raw `schedule.ics` URL
(File > New Calendar Subscription). That needs a public URL or a token-protected host — the
timetable contains teacher names and rooms, so decide deliberately.

Known school-year data (as of 2026-10-20): 23 weeks have entries (block schedule), from 2026-09-14 to 2027-07-09.
