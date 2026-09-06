"""
Load a user-supplied prayer time schedule from a CSV or JSON file. This
takes top priority over the online source and local calculation, for
whichever dates it covers.

CSV format (one row per date, 24-hour times):

    date,Fajr,Sunrise,Dhuhr,Asr,Maghrib,Isha
    2026-09-05,05:05,06:50,13:34,17:12,20:15,22:00
    2026-09-06,05:07,06:52,13:33,17:10,20:12,21:57

JSON format (one entry per date, 24-hour times):

    {
      "2026-09-05": {"Fajr": "05:05", "Sunrise": "06:50", "Dhuhr": "13:34",
                      "Asr": "17:12", "Maghrib": "20:15", "Isha": "22:00"},
      "2026-09-06": {"Fajr": "05:07", "Sunrise": "06:52", "Dhuhr": "13:33",
                      "Asr": "17:10", "Maghrib": "20:12", "Isha": "21:57"}
    }
"""

import csv
import json
from datetime import date

from prayer_calc import info_from_hhmm, PRAYER_ORDER

# Sunrise is optional in a custom schedule since it isn't a prayer.
REQUIRED_KEYS = [k for k in PRAYER_ORDER if k != "Sunrise"]


def load_custom_schedule(path: str) -> dict:
    """Returns {"YYYY-MM-DD": {"Fajr": "HH:MM", ...}, ...} with raw strings."""
    if path.lower().endswith(".json"):
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        schedule = {}
        for date_str, times in raw.items():
            schedule[date_str] = {k: times[k] for k in PRAYER_ORDER if k in times}
        return schedule

    if path.lower().endswith(".csv"):
        schedule = {}
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                date_str = row["date"].strip()
                schedule[date_str] = {
                    k: row[k].strip() for k in PRAYER_ORDER if k in row and row[k].strip()
                }
        return schedule

    raise ValueError("Unsupported file type — please choose a .csv or .json file.")


def get_times_for_date(schedule: dict, d: date):
    """
    Returns {"Fajr": {"display": ..., "hour": .., "minute": ..}, ...} for
    the given date if the schedule covers it and includes every required
    prayer, otherwise None (so the caller falls back to another source).
    """
    entry = schedule.get(d.strftime("%Y-%m-%d"))
    if not entry or not all(k in entry for k in REQUIRED_KEYS):
        return None
    return {name: info_from_hhmm(value) for name, value in entry.items()}