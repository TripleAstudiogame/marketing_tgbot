from __future__ import annotations

from app.bot import create_dispatcher


def test_create_dispatcher_can_be_called_multiple_times() -> None:
    first = create_dispatcher()
    second = create_dispatcher()

    assert first is not second
