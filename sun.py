"""Sonnenauf- und -untergang (NOAA-Naeherung, ~1 min genau) in Ortszeit.

Die alte PIR-Rechnung zog fest eine Stunde fuer MEZ ab und lag im Sommer
eine Stunde daneben. Hier rechnet ``zoneinfo`` die Sommerzeit.
"""
import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LAT = 52.4815     # Berlin-Neukoelln (wie der Wetter-Controller)
LON = 13.4300
TZ = ZoneInfo("Europe/Berlin")
ZENITH = 90.833   # Sonnenrand + Refraktion


def _utc_event(d, rising, lat=LAT, lon=LON):
    n = d.timetuple().tm_yday
    lng_hour = lon / 15.0
    t = n + ((6 if rising else 18) - lng_hour) / 24.0
    M = 0.9856 * t - 3.289
    L = (M + 1.916 * math.sin(math.radians(M)) + 0.020 * math.sin(math.radians(2 * M)) + 282.634) % 360
    RA = math.degrees(math.atan(0.91764 * math.tan(math.radians(L)))) % 360
    RA = (RA + (math.floor(L / 90) * 90 - math.floor(RA / 90) * 90)) / 15.0
    sin_dec = 0.39782 * math.sin(math.radians(L))
    cos_dec = math.cos(math.asin(sin_dec))
    cos_h = (math.cos(math.radians(ZENITH)) - sin_dec * math.sin(math.radians(lat))) / (
        cos_dec * math.cos(math.radians(lat)))
    if cos_h > 1 or cos_h < -1:
        return None   # Polarnacht/-tag — in Berlin nie
    H = (360 - math.degrees(math.acos(cos_h))) if rising else math.degrees(math.acos(cos_h))
    T = H / 15.0 + RA - 0.06571 * t - 6.622
    ut = (T - lng_hour) % 24
    base = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return base + timedelta(hours=ut)


def sun_times(d=None, lat=LAT, lon=LON):
    """{'sunrise': datetime, 'sunset': datetime} in Europe/Berlin fuer Datum ``d``."""
    d = d or datetime.now(TZ).date()
    out = {}
    for key, rising in (("sunrise", True), ("sunset", False)):
        ev = _utc_event(d, rising, lat, lon)
        if ev is not None:
            local = ev.astimezone(TZ)
            # NOAA rechnet in UTC-Tagen; liegt das Ereignis lokal am Nachbartag, verschieben
            if local.date() != d:
                ev = _utc_event(d + timedelta(days=(d - local.date()).days), rising, lat, lon)
                local = ev.astimezone(TZ)
            out[key] = local
    return out


def is_dark(now=None):
    now = now or datetime.now(TZ)
    st = sun_times(now.date())
    return now < st["sunrise"] or now >= st["sunset"]


def today():
    return datetime.now(TZ).date()


__all__ = ["sun_times", "is_dark", "TZ", "today", "date"]
