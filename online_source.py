"""
Fetches today's Edmonton prayer times from the AlAdhan API
(https://aladhan.com / api.aladhan.com), run by Islamic Network.

AlAdhan has been running since 2013, is free, actively maintained,
lists Edmonton specifically, and supports every major calculation
method. It's the reliable, well-known source this app leans on.

If the request fails for any reason (no internet, timeout, etc.),
every function here returns None so the caller can fall back to
local calculation instead of crashing.
"""

import json
import urllib.request
import urllib.error
from datetime import date

from prayer_calc import info_from_hhmm

EDMONTON_LAT = 53.5461
EDMONTON_LON = -113.4938

# AlAdhan's numeric codes for each calculation method.
ALADHAN_METHOD_CODES = {
    "Muslim World League (MWL)": 3,
    "ISNA (North America)": 2,
    "Egyptian General Authority": 5,
    "Umm al-Qura (Makkah)": 4,
    "University of Islamic Sciences, Karachi": 1,
}

PRAYER_KEYS = ("Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha")


def fetch_online_times(d: date, method_name: str, asr_hanafi: bool, timeout: float = 6.0):
    """
    Returns {"Fajr": {"display": ..., "hour": .., "minute": ..}, ...} on
    success, or None if the request fails for any reason.
    """
    method_code = ALADHAN_METHOD_CODES.get(method_name, 2)
    school = 1 if asr_hanafi else 0
    date_str = d.strftime("%d-%m-%Y")
    url = (
        f"https://api.aladhan.com/v1/timings/{date_str}"
        f"?latitude={EDMONTON_LAT}&longitude={EDMONTON_LON}"
        f"&method={method_code}&school={school}"
    )
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        timings = payload["data"]["timings"]
        result = {}
        for name in PRAYER_KEYS:
            raw = timings[name]  # e.g. "05:05 (MDT)"
            hhmm = raw.split(" ")[0]
            result[name] = info_from_hhmm(hhmm)
        return result
    except (urllib.error.URLError, KeyError, ValueError, TimeoutError, OSError):
        return None