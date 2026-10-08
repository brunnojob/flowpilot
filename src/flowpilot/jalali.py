"""Gregorian → Jalali (Solar Hijri / Persian) calendar conversion.

Pure-Python, dependency-free; used by the ``jalali`` template filter so that
messages can show Iranian dates, e.g. ``{{ now('Asia/Tehran') | jalali }}``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

MONTHS_FA = [
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
]
MONTHS_EN = [
    "Farvardin",
    "Ordibehesht",
    "Khordad",
    "Tir",
    "Mordad",
    "Shahrivar",
    "Mehr",
    "Aban",
    "Azar",
    "Dey",
    "Bahman",
    "Esfand",
]
WEEKDAYS_FA = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """Convert a Gregorian date to ``(year, month, day)`` in the Jalali calendar."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666
        + 365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        + gd
        + g_d_m[gm - 1]
    )
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd


def fa_digits(value: Any) -> str:
    """Replace ASCII digits with Persian digits."""
    return str(value).translate(_FA_DIGITS)


def format_jalali(value: Any = None, fmt: str = "%Y/%m/%d", persian_digits: bool = False) -> str:
    """Format a date/datetime/ISO string as Jalali.

    Supported directives: ``%Y`` ``%m`` ``%d`` ``%B`` (Persian month name),
    ``%b`` (transliterated month name), ``%A`` (Persian weekday), ``%H`` ``%M`` ``%S``.
    """
    if value is None:
        value = datetime.now()
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, date):
        raise TypeError(f"jalali: cannot format {type(value).__name__}")
    jy, jm, jd = gregorian_to_jalali(value.year, value.month, value.day)
    out = (
        fmt.replace("%Y", f"{jy:04d}")
        .replace("%m", f"{jm:02d}")
        .replace("%d", f"{jd:02d}")
        .replace("%B", MONTHS_FA[jm - 1])
        .replace("%b", MONTHS_EN[jm - 1])
        .replace("%A", WEEKDAYS_FA[value.weekday()])
    )
    if isinstance(value, datetime):
        out = out.replace("%H", f"{value.hour:02d}").replace("%M", f"{value.minute:02d}")
        out = out.replace("%S", f"{value.second:02d}")
    return fa_digits(out) if persian_digits else out
