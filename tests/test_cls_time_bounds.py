from __future__ import annotations

from dr_panda_mcp.guards import cls as cls_guard


def test_cls_rejects_absurd_year() -> None:
    # Must be parseable by datetime (max year 9999) but outside 2000–2100.
    decision = cls_guard.check_cls(
        "search_log",
        {
            "from": "2199-01-01T00:00:00+00:00",
            "to": "2199-01-01T01:00:00+00:00",
        },
    )
    assert decision.allowed is False
    assert decision.reason == "cls.invalid_timestamp"


def test_cls_accepts_normal_window() -> None:
    decision = cls_guard.check_cls(
        "search_log",
        {
            "from": "2026-11-10T00:00:00+00:00",
            "to": "2026-11-10T00:30:00+00:00",
        },
    )
    assert decision.allowed is True
