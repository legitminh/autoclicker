import sys
from types import SimpleNamespace

import pytest

from autoclicker import macos


@pytest.fixture
def quartz(monkeypatch):
    calls = []
    fake = SimpleNamespace(
        kCGEventSourceStatePrivate=-1,
        kCGEventLeftMouseDown=1,
        kCGEventLeftMouseUp=2,
        kCGMouseButtonLeft=0,
        kCGMouseEventClickState=1,
        kCGHIDEventTap=0,
        CGEventSourceCreate=lambda state: "source",
        CGEventCreateMouseEvent=lambda source, kind, point, button: (kind, point),
        CGEventSetIntegerValueField=lambda event, field, value: calls.append(
            ("click-state", event, value)
        ),
        CGWarpMouseCursorPosition=lambda point: calls.append(("warp", point)),
        CGEventSetTimestamp=lambda event, stamp: calls.append(("timestamp", event, stamp)),
        CGEventPost=lambda tap, event: calls.append(("post", event)),
    )
    monkeypatch.setitem(sys.modules, "Quartz", fake)
    monkeypatch.setattr(macos, "can_click", lambda: True)
    monkeypatch.setattr(macos, "monotonic_ns", lambda: 123456789)
    return fake, calls


def test_prepared_click_does_not_post_until_dispatch(quartz):
    _, calls = quartz
    click = macos.prepare_click(-120, 250)
    assert calls == [
        ("click-state", (1, (-120, 250)), 1),
        ("click-state", (2, (-120, 250)), 1),
    ]
    click()
    assert calls[2:] == [
        ("warp", (-120, 250)),
        ("timestamp", (1, (-120, 250)), 123456789),
        ("post", (1, (-120, 250))),
        ("timestamp", (2, (-120, 250)), 123456789),
        ("post", (2, (-120, 250))),
    ]


def test_revoked_permission_posts_nothing(quartz, monkeypatch):
    _, calls = quartz
    click = macos.prepare_click(20, 50)
    monkeypatch.setattr(macos, "can_click", lambda: False)
    with pytest.raises(RuntimeError, match="permission was removed"):
        click()
    assert not any(call[0] == "post" for call in calls)


def test_allocation_failure_posts_nothing(quartz):
    fake, calls = quartz
    fake.CGEventCreateMouseEvent = lambda *args: None
    with pytest.raises(RuntimeError, match="could not create the click events"):
        macos.prepare_click(20, 50)
    assert calls == []
