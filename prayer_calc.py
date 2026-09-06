"""
Prayer time calculation engine.

Uses standard solar-position astronomical formulas (equation of time,
solar declination, hour angles) to compute the five daily prayers plus
sunrise for a given date, latitude, longitude and UTC offset.

Accuracy is typically within a minute of official published tables,
which is normal for this style of calculation. For exact certainty
(e.g. for a mosque), always cross-check with a local authority.
"""

import math
from datetime import date

# Fajr/Isha angle definitions per calculation method.
# isha_minutes overrides the angle with a fixed offset after Maghrib.
METHODS = {
    "Muslim World League (MWL)": {"fajr": 18.0, "isha": 17.0, "isha_minutes": None},
    "ISNA (North America)": {"fajr": 15.0, "isha": 15.0, "isha_minutes": None},
    "Egyptian General Authority": {"fajr": 19.5, "isha": 17.5, "isha_minutes": None},
    "Umm al-Qura (Makkah)": {"fajr": 18.5, "isha": None, "isha_minutes": 90},
    "University of Islamic Sciences, Karachi": {"fajr": 18.0, "isha": 18.0, "isha_minutes": None},
}

ASR_FACTORS = {
    "Standard (Shafi/Maliki/Hanbali)": 1,
    "Hanafi": 2,
}

PRAYER_ORDER = ["Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha"]


def _julian_day(d: date) -> float:
    y, m, day = d.year, d.month, d.day
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + day + b - 1524.5


def _sun_position(jd: float):
    """Return (declination_rad, equation_of_time_hours) for a Julian day."""
    d = jd - 2451545.0
    g = math.radians((357.529 + 0.98560028 * d) % 360)
    q = (280.459 + 0.98564736 * d) % 360
    l = math.radians((q + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)) % 360)
    e = math.radians(23.439 - 0.00000036 * d)

    decl = math.asin(math.sin(e) * math.sin(l))
    ra = math.degrees(math.atan2(math.cos(e) * math.sin(l), math.cos(l))) / 15.0
    ra = ra % 24
    eq_time = q / 15.0 - ra
    if eq_time > 12:
        eq_time -= 24
    if eq_time < -12:
        eq_time += 24
    return decl, eq_time


def _hour_angle(lat_rad, decl, angle_deg):
    angle = math.radians(angle_deg)
    cos_ha = (-math.sin(angle) - math.sin(lat_rad) * math.sin(decl)) / (
        math.cos(lat_rad) * math.cos(decl)
    )
    cos_ha = max(-1.0, min(1.0, cos_ha))
    return math.degrees(math.acos(cos_ha))


def _asr_hour_angle(lat_rad, decl, factor):
    # Angle of the sun above the horizon when Asr begins (arccot form).
    angle_deg = -math.degrees(math.atan(1.0 / (factor + math.tan(abs(lat_rad - decl)))))
    return _hour_angle(lat_rad, decl, angle_deg)


def _to_hhmm(hours: float) -> str:
    hours = hours % 24
    h = int(hours)
    m = int(round((hours - h) * 60))
    if m == 60:
        m = 0
        h = (h + 1) % 24
    period = "AM" if h < 12 else "PM"
    h12 = h % 12
    if h12 == 0:
        h12 = 12
    return f"{h12:02d}:{m:02d} {period}"


def _to_24h_tuple(hours: float):
    hours = hours % 24
    h = int(hours)
    m = int(round((hours - h) * 60))
    if m == 60:
        m = 0
        h = (h + 1) % 24
    return h, m


def calculate_prayer_times(d: date, lat: float, lon: float, utc_offset: float,
                            method: str = "ISNA (North America)",
                            asr_method: str = "Standard (Shafi/Maliki/Hanbali)"):
    """
    Returns a dict: prayer name -> {"display": "HH:MM AM/PM", "hour": h, "minute": m}
    for the given date and location.
    """
    params = METHODS[method]
    lat_rad = math.radians(lat)

    jd = _julian_day(d) - lon / 360.0
    decl, eq_time = _sun_position(jd)

    solar_noon = 12 + utc_offset - lon / 15.0 - eq_time

    fajr_ha = _hour_angle(lat_rad, decl, params["fajr"])
    sunrise_ha = _hour_angle(lat_rad, decl, 0.833)  # atmospheric refraction correction
    asr_ha = _asr_hour_angle(lat_rad, decl, ASR_FACTORS[asr_method])
    maghrib_ha = sunrise_ha

    fajr = solar_noon - fajr_ha / 15.0
    sunrise = solar_noon - sunrise_ha / 15.0
    dhuhr = solar_noon + 1.0 / 60.0
    asr = solar_noon + asr_ha / 15.0
    maghrib = solar_noon + maghrib_ha / 15.0

    if params["isha_minutes"] is not None:
        isha = maghrib + params["isha_minutes"] / 60.0
    else:
        isha_ha = _hour_angle(lat_rad, decl, params["isha"])
        isha = solar_noon + isha_ha / 15.0

    raw = {"Fajr": fajr, "Sunrise": sunrise, "Dhuhr": dhuhr,
           "Asr": asr, "Maghrib": maghrib, "Isha": isha}

    result = {}
    for name, value in raw.items():
        h, m = _to_24h_tuple(value)
        result[name] = {"display": _to_hhmm(value), "hour": h, "minute": m}
    return result
def info_from_hhmm(hhmm: str) -> dict:
    """
    Convert a 24-hour "HH:MM" string (e.g. from an online API or a custom
    import file) into the same {"display", "hour", "minute"} shape used
    everywhere else in the app.
    """
    h_str, m_str = hhmm.strip().split(":")
    h, m = int(h_str), int(m_str)
    period = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return {"display": f"{h12:02d}:{m:02d} {period}", "hour": h, "minute": m}