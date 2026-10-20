#!/bin/bash
# Remove old "Munich Maker Lab" events from Apple Calendar (macOS).
# Dry run by default: lists matches and deletes nothing.
#   ./remove_maker_lab.sh            -> list only
#   ./remove_maker_lab.sh --delete   -> actually delete (Calendar has no trash for scripted deletes: export a backup first)
# Matches events whose TITLE contains "Munich Maker Lab" (case-insensitive) in ANY calendar.
# If the old events live in their own calendar, it is simpler to delete that calendar
# in Calendar.app (right-click > Delete) instead of using this script.

MODE="list"; [ "$1" = "--delete" ] && MODE="delete"

osascript - "$MODE" <<'APPLESCRIPT'
on run argv
  set mode to item 1 of argv
  set hits to 0
  tell application "Calendar"
    repeat with cal in calendars
      try
        set evs to (every event of cal whose summary contains "Maker Lab")
        repeat with ev in evs
          if (summary of ev) contains "Munich Maker Lab" or (summary of ev) contains "munich maker lab" then
            set hits to hits + 1
            log (name of cal) & " | " & (start date of ev as string) & " | " & (summary of ev)
            if mode is "delete" then delete ev
          end if
        end repeat
      end try
    end repeat
  end tell
  return (hits as string) & " matching event(s), mode=" & mode
end run
APPLESCRIPT
