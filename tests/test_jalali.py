from __future__ import annotations

from datetime import date, datetime

import pytest

from flowpilot.jalali import fa_digits, format_jalali, gregorian_to_jalali


@pytest.mark.parametrize(
    ("greg", "jal"),
    [
        ((2023, 3, 21), (1402, 1, 1)),
        ((2024, 3, 20), (1403, 1, 1)),
        ((2025, 3, 21), (1404, 1, 1)),
        ((2026, 10, 8), (1405, 7, 16)),
        ((1979, 2, 11), (1357, 11, 22)),
        ((2000, 1, 1), (1378, 10, 11)),
    ],
)
def test_known_dates(greg, jal):
    assert gregorian_to_jalali(*greg) == jal


def test_format_and_digits():
    d = datetime(2026, 10, 8, 9, 5, 7)
    assert format_jalali(d, "%Y/%m/%d %H:%M:%S") == "1405/07/16 09:05:07"
    assert format_jalali(date(2026, 10, 8), "%d %B %Y") == "16 مهر 1405"
    assert format_jalali(date(2026, 10, 8), "%b") == "Mehr"
    assert format_jalali(date(2026, 10, 8), "%A") == "پنجشنبه"
    assert format_jalali("2026-10-08T00:00:00Z", persian_digits=True) == "۱۴۰۵/۰۷/۱۶"
    assert isinstance(format_jalali(), str)
    assert fa_digits("a1b2") == "a۱b۲"
    with pytest.raises(TypeError):
        format_jalali(123)
