# Automatic updates (private repo + secret gist feed)

WebUntis has no webhooks and (for this school) no iCal feed, so the workflow polls hourly and only
acts when the timetable really changed: it commits a snapshot, updates the feed, and opens a GitHub
issue listing the differences (`data/CHANGES.md`).

## One-time setup
1. Create a **private** GitHub repo; put this folder's contents at its root
   (`webuntis_sync.py`, `.github/workflows/webuntis-sync.yml`).
2. Create the feed once (secret gist = unlisted URL, not search-indexed):
   `gh gist create README.md --desc "timetable feed"` then note the gist ID. (Any placeholder file is fine; the
   workflow adds `schedule.ics` on the first change.)
3. Create a fine-grained/classic PAT with **only the `gist` scope** (the default Actions token cannot edit gists).
4. Repo > Settings > Secrets and variables > Actions, add:
   `WEBUNTIS_USER`, `WEBUNTIS_PASSWORD` (or `WEBUNTIS_COOKIE` for SSO), `GIST_TOKEN`, `GIST_ID`.
5. Actions tab > webuntis-sync > **Run workflow** once. The first run only creates the baseline (no issue).
6. Subscribe in Apple Calendar: File > New Calendar Subscription, URL
   `https://gist.githubusercontent.com/<your-user>/<GIST_ID>/raw/schedule.ics`
   (use `webcal://` instead of `https://` on iPhone). Set auto-refresh to hourly.

## Things to know
- Anyone with the gist URL can read the feed (teacher names, rooms, your work days). It is unlisted, not private.
- The WebUntis login step is untested; step 5 will show whether it works. If your school uses SSO, log in in
  the browser and store the session cookie as `WEBUNTIS_COOKIE` (it expires, so this needs occasional refresh).
- GitHub scheduled runs can be delayed by several minutes, and Apple decides how often subscribed calendars refresh.
  Expect changes to reach your calendar within roughly an hour or two, not instantly.
- Work days (09:00-17:00 on non-school weekdays, none on WebUntis holidays) are part of the feed. Tune with
  `--work-hours`, `--work-from`, `--no-work` in the workflow's run step.
