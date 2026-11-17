from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from autoclicker.app import Autoclicker, CaptureOverlay, ScheduleDialog
from autoclicker.timing import nearest_minute


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(app):
    result = ScheduleDialog(QPoint(120, 80), datetime.now(ZoneInfo("America/New_York")))
    result.show()
    app.processEvents()
    yield result
    result.close()
    result.deleteLater()
    app.processEvents()


def test_default_is_selection_time_rounded_to_nearest_minute(dialog):
    # Use a fixed timestamp so this test never straddles a minute boundary.
    clicked = datetime(2026, 11, 17, 23, 59, 40, tzinfo=ZoneInfo("America/New_York"))
    widget = ScheduleDialog(QPoint(120, 80), clicked)
    assert [field.value() for field in widget.fields] == [1, 0, 0, 0, 0]
    assert widget.target == nearest_minute(clicked)
    widget.close()


def test_tab_moves_between_time_fields(dialog, app):
    dialog.fields[0].setFocus()
    for next_field in dialog.fields[1:]:
        QTest.keyClick(app.focusWidget(), Qt.Key.Key_Tab)
        assert app.focusWidget() is next_field


def test_text_edit_updates_target_and_countdown(dialog):
    dialog.fields[0].setValue(2)
    dialog.fields[4].setFocus()
    dialog.fields[4].selectAll()
    QTest.keyClicks(dialog.fields[4], "123")
    assert dialog.target.microsecond == 123000
    assert dialog.target.date() == dialog.anchor + timedelta(days=2)
    assert dialog.countdown.text().startswith("In ")
    assert dialog.submit.isEnabled()


def test_countdown_ticks_without_editing(dialog):
    dialog.fields[0].setValue(1)
    before = dialog.countdown.text()
    QTest.qWait(120)
    assert dialog.countdown.text() != before


def test_past_time_cannot_be_armed(dialog):
    for field in dialog.fields:
        field.setValue(0)
    scheduled = []
    dialog.scheduled.connect(scheduled.append)
    dialog.arm()
    assert not dialog.submit.isEnabled()
    assert "future" in dialog.error.text()
    assert scheduled == []


def test_blank_field_cannot_be_armed(dialog):
    dialog.fields[0].setValue(1)
    dialog.fields[2].lineEdit().clear()
    dialog.refresh()
    assert not dialog.submit.isEnabled()


def test_selection_waits_for_release_and_remembers_press_position(app):
    overlay = CaptureOverlay(app.primaryScreen())
    overlay.show()
    selected = []
    overlay.selected.connect(lambda *args: selected.append(args))
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(80, 90))
    assert selected == []
    assert overlay.isVisible()
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(100, 110))
    assert len(selected) == 1
    assert selected[0][0] == overlay.mapToGlobal(QPoint(80, 90))
    overlay.close()


def test_arming_hides_dialog_before_starting_worker(app, dialog, monkeypatch):
    controller = Autoclicker(app)
    controller.dialog = dialog
    dialog.fields[0].setValue(1)
    calls = []
    monkeypatch.setattr("autoclicker.app.macos.prepare_click", lambda x, y: lambda: None)
    monkeypatch.setattr(controller, "make_tray", lambda target: None)

    class FakeJob:
        def __init__(self, deadline, click, finished, failed):
            assert not dialog.isVisible()

        def start(self):
            calls.append("started")

        def cancel(self):
            pass

        def join(self, timeout):
            pass

    monkeypatch.setattr("autoclicker.app.ScheduledClick", FakeJob)
    controller.arm(dialog.target)
    assert calls == ["started"]
