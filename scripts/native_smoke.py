"""Opt-in macOS end-to-end test. Sends two real clicks to THIS test's own button.

Run with `uv run python scripts/native_smoke.py`. Leave the pointer alone for
three seconds. The test verifies the selection click is swallowed, then exactly
one scheduled click reaches the test button and the application exits.
"""

from datetime import datetime, timedelta
from time import time_ns

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
from tzlocal import get_localzone

from autoclicker.app import Autoclicker
from autoclicker.macos import can_click, check_platform, single_click
from autoclicker.timing import epoch_ns


def main():
    check_platform()
    import Quartz

    if Quartz.CGSessionCopyCurrentDictionary().get("CGSSessionScreenIsLocked", False):
        print("SKIP: unlock the desktop before running the native input test.")
        return
    if not can_click():
        raise SystemExit("Grant Accessibility permission before running the native smoke test.")
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    button = QPushButton("Autoclicker test target — do not click manually")
    button.setGeometry(180, 240, 440, 140)
    clicks = []
    button.clicked.connect(lambda: clicks.append(time_ns()))
    button.show()
    app.processEvents()
    point = button.mapToGlobal(button.rect().center())
    controller = Autoclicker(app)
    failures = []
    target_ns = [None]

    def fail(message):
        failures.append(message)
        app.quit()

    def schedule():
        if clicks:
            return fail("The selection click fell through to the target button.")
        if controller.dialog is None:
            return fail("The native selection click did not reach the overlay.")
        assert controller.dialog.point == point
        print("Selection swallowed: target button has 0 clicks.", flush=True)
        target = datetime.now(get_localzone()) + timedelta(seconds=1)
        target = target.replace(microsecond=target.microsecond // 1000 * 1000)
        target_ns[0] = epoch_ns(target)
        fields = [
            (target.date() - controller.dialog.anchor).days,
            target.hour,
            target.minute,
            target.second,
            target.microsecond // 1000,
        ]
        for field, value in zip(controller.dialog.fields, fields, strict=True):
            field.setValue(value)
        controller.dialog.arm()

    def select():
        controller.select()
        QTimer.singleShot(200, lambda: single_click(point.x(), point.y()))
        QTimer.singleShot(500, schedule)

    QTimer.singleShot(200, select)
    QTimer.singleShot(5000, lambda: fail("The app did not exit after the scheduled click."))
    app.exec()
    # Posting a native event precedes delivery; allow the native event stream
    # to drain after the controller quits (the target lives in this process).
    QTest.qWait(100)
    button.close()
    if failures:
        raise SystemExit("FAIL: " + "; ".join(failures))
    if len(clicks) != 1:
        raise SystemExit(f"FAIL: expected 1 target click, received {len(clicks)}.")
    if target_ns[0] is None or clicks[0] < target_ns[0]:
        raise SystemExit("FAIL: the click arrived before the scheduled instant.")
    late_ms = (clicks[0] - target_ns[0]) / 1_000_000
    print(f"PASS: exactly 1 scheduled click, received {late_ms:.3f} ms after target; app exited.")


if __name__ == "__main__":
    main()
