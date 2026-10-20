#!/usr/bin/env python3
"""
WebUntis -> ICS / JSON / Markdown sync (student timetable, whole school year).

Re-runnable: every event gets a stable UID, so re-importing the .ics into Apple
Calendar UPDATES existing events (moved / cancelled / changed lessons) instead
of duplicating them. Every run also writes a dated snapshot you can reference
from GitHub issues.

Credentials are read from the environment only (never hard-code them):
    WEBUNTIS_USER, WEBUNTIS_PASSWORD

Usage:
    export WEBUNTIS_USER=...  WEBUNTIS_PASSWORD=...
    python3 webuntis_sync.py                       # default: 2026-08-03 .. 2027-08-31
    python3 webuntis_sync.py --start 2026-09-01 --end 2027-07-31
    python3 webuntis_sync.py --host bsinfo.webuntis.com --school bsinfo --student-id 21900

Output (in --out, default ./out):
    schedule.ics                 import / subscribe in Apple Calendar
    snapshots/YYYY-MM-DD.json    raw API data, dated (commit these)
    schedule.md                  readable week-by-week list, handy for issues
    CHANGES.md                   diff vs. the previous snapshot (what changed)

NOTE: the data endpoints (/api/rest/view/v1/timetable/entries) are the ones the
WebUntis web app itself uses. The username/password login step below follows the
standard WebUntis form login; if your school uses SSO, log in once in the browser
and pass the session cookie instead via WEBUNTIS_COOKIE="JSESSIONID=...; schoolname=...".
"""
import argparse, datetime as dt, hashlib, json, os, sys, urllib.parse, urllib.request
from http.cookiejar import CookieJar

SKIP_EVENT_NAMES = {"Pause", "Vor Unterrichtsbeginn", "Nach Unterrichtsende"}
TZ = "Europe/Berlin"

VTIMEZONE = """BEGIN:VTIMEZONE
TZID:Europe/Berlin
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE"""


# ---------------------------------------------------------------- API client
class Client:
    def __init__(self, host, school):
        self.base = f"https://{host}/WebUntis"
        self.school = school
        self.jar = CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.cookie_header = os.environ.get("WEBUNTIS_COOKIE")
        self.token = None

    def _req(self, path, data=None, headers=None):
        h = {"User-Agent": "webuntis-sync/1.0"}
        if self.cookie_header:
            h["Cookie"] = self.cookie_header
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, data=data, headers=h)
        with self.op.open(req, timeout=30) as r:
            return r.read().decode()

    def login(self):
        if not self.cookie_header:
            user, pw = os.environ.get("WEBUNTIS_USER"), os.environ.get("WEBUNTIS_PASSWORD")
            if not (user and pw):
                sys.exit("Set WEBUNTIS_USER and WEBUNTIS_PASSWORD (or WEBUNTIS_COOKIE).")
            form = urllib.parse.urlencode(
                {"school": self.school, "j_username": user, "j_password": pw, "token": ""}
            ).encode()
            self._req("/j_spring_security_check", form,
                      {"Content-Type": "application/x-www-form-urlencoded"})
        self.token = self._req("/api/token/new").strip()

    def student_id(self):
        d = json.loads(self._req("/api/rest/view/v1/app/data"))
        return d["user"]["person"]["id"]

    def week(self, student_id, monday):
        friday = monday + dt.timedelta(days=4)
        q = urllib.parse.urlencode({
            "start": monday.isoformat(), "end": friday.isoformat(), "format": 1,
            "resourceType": "STUDENT", "resources": student_id, "periodTypes": "",
            "timetableType": "MY_TIMETABLE", "layout": "START_TIME"})
        return json.loads(self._req(f"/api/rest/view/v1/timetable/entries?{q}"))


# ------------------------------------------------------------------ parsing
def names(pos):
    out = []
    for x in pos or []:
        c = x.get("current") or x.get("removed")
        if c:
            out.append((c.get("shortName") or "", c.get("longName") or c.get("shortName") or ""))
    return out


def parse_week(week_json):
    """Flatten one API week into simple event dicts."""
    events = []
    for day in week_json.get("days", []):
        for e in day.get("backEntries", []):
            if e.get("type") == "HOLIDAY":
                events.append(dict(uid_key=f"holiday-{day['date']}", kind="holiday",
                                   title="Schulfrei / Ferien", date=day["date"],
                                   status="REGULAR", all_day=True))
        for e in day.get("gridEntries", []):
            teachers, subject, room = names(e.get("position1")), names(e.get("position2")), names(e.get("position3"))
            if e.get("type") == "EVENT" and subject == [] and teachers and teachers[0][0] in SKIP_EVENT_NAMES:
                continue
            if e.get("type") == "EVENT" and teachers and teachers[0][0] in SKIP_EVENT_NAMES:
                continue
            title = (subject[0][1] if subject else (e.get("name") or "Lesson"))
            events.append(dict(
                uid_key=f"{e['ids'][0] if e.get('ids') else 'x'}-{e['duration']['start']}-{title}",
                kind=e.get("type"), title=title,
                start=e["duration"]["start"], end=e["duration"]["end"],
                teachers=sorted({t[1] for t in teachers}), room=room[0][0] if room else "",
                status=e.get("status", "REGULAR"), notes=(e.get("notesAll") or "").strip(),
                all_day=False))
    return events


def add_work_days(events, start, end, t0="09:00", t1="17:00", title="Arbeit"):
    """Add a work event on every Mon-Fri with no (non-cancelled) lesson and no WebUntis holiday."""
    school, off = set(), set()
    for e in events:
        if e["all_day"]:
            off.add(e["date"])
        elif e["status"] != "CANCELLED" and e["kind"] in ("NORMAL_TEACHING_PERIOD", "ADDITIONAL_PERIOD", "EVENT"):
            school.add(e["start"][:10])
    d = start
    while d <= end:
        iso = d.isoformat()
        if d.weekday() < 5 and iso not in school and iso not in off:
            events.append(dict(uid_key=f"work-{iso}", kind="work", title=title, start=f"{iso}T{t0}",
                               end=f"{iso}T{t1}", teachers=[], room="", status="REGULAR", notes="", all_day=False))
        d += dt.timedelta(days=1)
    return events


# ---------------------------------------------------------------------- ICS
def esc(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    """RFC 5545 line folding (75 octets, never splitting a UTF-8 character)."""
    b, parts, limit = line.encode(), [], 75
    while len(b) > limit:
        cut = limit
        while (b[cut] & 0xC0) == 0x80:
            cut -= 1
        parts.append(b[:cut].decode())
        b, limit = b[cut:], 74
    parts.append(b.decode())
    return "\r\n ".join(parts)


def ics_dt(s):
    return dt.datetime.fromisoformat(s).strftime("%Y%m%dT%H%M%S")


def build_ics(events, now=None):
    now = (now or dt.datetime.utcnow()).strftime("%Y%m%dT%H%M%SZ")
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//webuntis-sync//DE", "CALSCALE:GREGORIAN",
         "METHOD:PUBLISH", "X-WR-CALNAME:Berufsschule (WebUntis)", f"X-WR-TIMEZONE:{TZ}", VTIMEZONE]
    for ev in events:
        uid = hashlib.sha1(ev["uid_key"].encode()).hexdigest()[:24] + "@webuntis-sync"
        L += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{now}"]
        if ev["all_day"]:
            d = dt.date.fromisoformat(ev["date"])
            L += [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + dt.timedelta(days=1):%Y%m%d}"]
            L += [f"SUMMARY:{esc(ev['title'])}", "TRANSP:TRANSPARENT"]
        else:
            L += [f"DTSTART;TZID={TZ}:{ics_dt(ev['start'])}", f"DTEND;TZID={TZ}:{ics_dt(ev['end'])}"]
            prefix = {"CANCELLED": "ENTFALL: ", "CHANGED": "", "ADDITIONAL": "Zusatz: "}.get(ev["status"], "")
            L.append(f"SUMMARY:{esc(prefix + ev['title'])}")
            if ev["room"]:
                L.append(f"LOCATION:{esc(ev['room'])}")
            desc = []
            if ev["teachers"]:
                desc.append("Lehrkraft: " + ", ".join(ev["teachers"]))
            if ev["notes"]:
                desc.append(ev["notes"])
            if ev["status"] != "REGULAR":
                desc.append(f"Status: {ev['status']}")
            if desc:
                L.append(f"DESCRIPTION:{esc(chr(10).join(desc))}")
            if ev["status"] == "CANCELLED":
                L += ["STATUS:CANCELLED"]
        L.append("END:VEVENT")
    L.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in L) + "\r\n"


# ----------------------------------------------------------------- Markdown
def build_md(events, generated):
    lines = [f"# Stundenplan (generated {generated})", ""]
    by_day = {}
    for ev in events:
        d = ev["date"] if ev["all_day"] else ev["start"][:10]
        by_day.setdefault(d, []).append(ev)
    cur_week = None
    for d in sorted(by_day):
        day = dt.date.fromisoformat(d)
        wk = day - dt.timedelta(days=day.weekday())
        if wk != cur_week:
            cur_week = wk
            lines += ["", f"## Week of {wk} (KW {wk.isocalendar()[1]})", ""]
        for ev in sorted(by_day[d], key=lambda e: e.get("start", "")):
            if ev["all_day"]:
                lines.append(f"- {d} {day:%a}: **{ev['title']}**")
            else:
                flag = "" if ev["status"] == "REGULAR" else f" _({ev['status'].lower()})_"
                lines.append(f"- {d} {day:%a} {ev['start'][11:16]}-{ev['end'][11:16]} "
                             f"{ev['title']} [{ev['room']}] {', '.join(ev['teachers'])}{flag}"
                             + (f" — {ev['notes']}" if ev["notes"] else ""))
    return "\n".join(lines) + "\n"


def diff(old, new):
    key = lambda e: e["uid_key"]
    o, n = {key(e): e for e in old}, {key(e): e for e in new}
    out = []
    for k in n.keys() - o.keys():
        out.append(f"+ new: {n[k]['title']} {n[k].get('start', n[k].get('date'))}")
    for k in o.keys() - n.keys():
        out.append(f"- gone: {o[k]['title']} {o[k].get('start', o[k].get('date'))}")
    for k in n.keys() & o.keys():
        if (o[k]["status"], o[k]["room"] if "room" in o[k] else "", o[k].get("notes")) != \
           (n[k]["status"], n[k]["room"] if "room" in n[k] else "", n[k].get("notes")):
            what = []
            for fld in ("status", "room", "notes"):
                ov, nv = o[k].get(fld, ""), n[k].get(fld, "")
                if ov != nv:
                    what.append(f"{fld}: {ov or '-'} -> {nv or '-'}")
            out.append(f"~ changed: {n[k]['title']} {n[k].get('start')} ({'; '.join(what)})")
    return sorted(out)


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="bsinfo.webuntis.com")
    ap.add_argument("--school", default="bsinfo")
    ap.add_argument("--student-id", type=int)
    ap.add_argument("--start", default="2026-08-03")
    ap.add_argument("--end", default="2027-08-31")
    ap.add_argument("--out", default="out")
    ap.add_argument("--no-work", action="store_true", help="do not add work events on non-school weekdays")
    ap.add_argument("--work-from", default="2026-09-01")
    ap.add_argument("--work-hours", default="09:00-17:00")
    ap.add_argument("--work-title", default="Arbeit")
    a = ap.parse_args()

    c = Client(a.host, a.school); c.login()
    sid = a.student_id or c.student_id()
    d = dt.date.fromisoformat(a.start); d -= dt.timedelta(days=d.weekday())
    end = dt.date.fromisoformat(a.end)
    raw, events = {}, []
    while d <= end:
        wk = c.week(sid, d)
        if any(day.get("gridEntries") or day.get("backEntries") for day in wk.get("days", [])):
            raw[d.isoformat()] = wk
            events += parse_week(wk)
        d += dt.timedelta(days=7)

    if not a.no_work:
        t0, t1 = a.work_hours.split("-")
        add_work_days(events, dt.date.fromisoformat(a.work_from), end, t0, t1, a.work_title)

    changed, changes = write_outputs(a.out, raw, events)
    print(f"{len(raw)} weeks with data, {len(events)} events, "
          f"{'CHANGED (' + str(len(changes)) + ' differences)' if changed else 'no change'}")
    # Expose the result to GitHub Actions (steps can branch on `changed`).
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"changed={'true' if changed else 'false'}\n")
            fh.write(f"initial={'true' if changed and not changes else 'false'}\n")


def write_outputs(out, raw, events, now=None):
    """Write files only when the timetable differs from the last stored state.

    Returns (changed, changes). `changes` is empty on the very first run.
    Files: events.json (current state), schedule.ics, schedule.md, CHANGES.md,
    snapshots/<UTC timestamp>.json (raw API data, one per change).
    """
    now = now or dt.datetime.utcnow()
    state = f"{out}/events.json"
    old = json.load(open(state)) if os.path.exists(state) else None
    changes = diff(old, events) if old is not None else []
    if old is not None and not changes:
        return False, []
    os.makedirs(f"{out}/snapshots", exist_ok=True)
    stamp = now.strftime("%Y-%m-%dT%H%M%SZ")
    with open(f"{out}/snapshots/{stamp}.json", "w") as f:
        json.dump(raw, f, ensure_ascii=False, indent=1)
    with open(state, "w") as f:
        json.dump(events, f, ensure_ascii=False, indent=1)
    open(f"{out}/schedule.ics", "w", newline="").write(build_ics(events, now))
    open(f"{out}/schedule.md", "w").write(build_md(events, now.date().isoformat()))
    if old is not None:
        open(f"{out}/CHANGES.md", "w").write(
            f"# Timetable changes detected {stamp}\n\n" + "\n".join(f"- {c}" for c in changes) + "\n")
    return True, changes


if __name__ == "__main__":
    main()
