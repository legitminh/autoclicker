"""Pick a point without clicking through, then schedule one local-time click."""

import signal
import sys
from datetime import datetime
from time import time_ns

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontDatabase, QIcon, QKeyEvent, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)
from tzlocal import get_localzone

from . import macos
from .timing import ScheduledClick, epoch_ns, local_candidates, nearest_minute, relative_text


class CaptureOverlay(QWidget):
    selected = Signal(QPoint, object)
    cancelled = Signal()

    def __init__(self, screen) -> None:
        super().__init__(
            None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(screen.geometry())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._press: tuple[QPoint, datetime] | None = None

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        # Fully transparent pixels can be click-through on macOS. Paint EVERY
        # pixel with a nonzero alpha so the whole screen intercepts the click.
        painter.fillRect(self.rect(), QColor(12, 18, 30, 35))
        box = self.rect().adjusted(30, 40, -30, 0)
        box.setHeight(80)
        painter.fillRect(box, QColor(22, 25, 33, 235))
        painter.setPen(QColor("white"))
        font = painter.font()
        font.setPointSize(17)
        painter.setFont(font)
        painter.drawText(
            box,
            Qt.AlignmentFlag.AlignCenter,
            "Click a point to schedule one click\nSelection will not click through · Esc to cancel",
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        event.accept()
        if event.button() == Qt.MouseButton.LeftButton and self._press is None:
            self._press = (event.globalPosition().toPoint(), datetime.now(get_localzone()))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        event.accept()
        # Keep every overlay in place until release: swallowing only the press
        # could deliver an orphaned release to the application underneath.
        if event.button() == Qt.MouseButton.LeftButton and self._press is not None:
            point, clicked_at = self._press
            self._press = None
            self.selected.emit(point, clicked_at)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
        event.accept()


class TimeField(QSpinBox):
    def __init__(self, maximum: int, digits: int, name: str) -> None:
        super().__init__()
        self.digits = digits
        self.setRange(0, maximum)
        self.setAccessibleName(name)
        self.setMinimumWidth(76 if digits < 4 else 90)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWrapping(False)

    def textFromValue(self, value: int) -> str:
        return f"{value:0{self.digits}d}"


class ScheduleDialog(QDialog):
    scheduled = Signal(object)

    def __init__(self, point: QPoint, clicked_at: datetime) -> None:
        super().__init__()
        self.setWindowTitle("Schedule one click")
        self.point = point
        self.zone = clicked_at.tzinfo
        self.anchor = clicked_at.date()
        self.target: datetime | None = None
        self.setMinimumWidth(540)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        heading = QLabel("When should I click?")
        heading.setStyleSheet("font-size: 24px; font-weight: 600;")
        layout.addWidget(heading)
        layout.addWidget(QLabel(f"One left click at ({point.x()}, {point.y()})"))
        zone_name = getattr(self.zone, "key", str(self.zone))
        timezone_label = QLabel(f"Local time · {zone_name}")
        timezone_label.setWordWrap(True)
        layout.addWidget(timezone_label)

        grid = QGridLayout()
        self.fields = [
            TimeField(maximum, digits, name)
            for name, maximum, digits in (
                ("Days", 9999, 1),
                ("Hour", 23, 2),
                ("Minute", 59, 2),
                ("Second", 59, 2),
                ("Millisecond", 999, 3),
            )
        ]
        for index, (name, field) in enumerate(
            zip(("Days", "Hour", "Minute", "Second", "Millisecond"), self.fields, strict=True)
        ):
            label = QLabel(name)
            label.setBuddy(field)
            grid.addWidget(label, 0, index)
            grid.addWidget(field, 1, index)
        layout.addLayout(grid)
        anchor_label = QLabel(
            f"Days after {self.anchor:%b %d, %Y} · 24-hour clock · Tab to move between fields"
        )
        anchor_label.setWordWrap(True)
        layout.addWidget(anchor_label)

        self.occurrence = QComboBox()
        self.occurrence.setAccessibleName("Repeated hour occurrence")
        self.occurrence.hide()
        layout.addWidget(self.occurrence)
        self.resolved = QLabel()
        self.resolved.setWordWrap(True)
        layout.addWidget(self.resolved)
        self.countdown = QLabel()
        countdown_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        countdown_font.setPixelSize(22)
        self.countdown.setFont(countdown_font)
        layout.addWidget(self.countdown)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #ce5757;")
        layout.addWidget(self.error)

        buttons = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        self.submit = QPushButton("Schedule click")
        self.submit.setDefault(True)
        self.submit.clicked.connect(self.arm)
        buttons.addWidget(cancel)
        buttons.addStretch()
        buttons.addWidget(self.submit)
        layout.addLayout(buttons)

        rounded = nearest_minute(clicked_at)
        initial = (
            (rounded.date() - self.anchor).days,
            rounded.hour,
            rounded.minute,
            rounded.second,
            rounded.microsecond // 1000,
        )
        for field, value in zip(self.fields, initial, strict=True):
            field.setValue(value)
            field.textChanged.connect(self.refresh)
        for first, second in zip(self.fields, self.fields[1:], strict=False):
            QWidget.setTabOrder(first, second)
        self.occurrence.currentIndexChanged.connect(self.refresh)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(50)
        self.refresh()
        if rounded.fold and self.occurrence.count() == 2:
            self.occurrence.setCurrentIndex(1)
        self.fields[1].setFocus()
        self.fields[1].selectAll()

    def refresh(self, *_args) -> None:
        try:
            if any(not field.hasAcceptableInput() for field in self.fields):
                raise ValueError("Complete every time field.")
            candidates = local_candidates(
                self.anchor, *(field.value() for field in self.fields), self.zone
            )
            labels = [
                f"{'Earlier' if index == 0 else 'Later'} occurrence · {value:%Z (UTC%z)}"
                for index, value in enumerate(candidates)
            ]
            if [self.occurrence.itemText(i) for i in range(self.occurrence.count())] != labels:
                index = max(0, self.occurrence.currentIndex())
                self.occurrence.blockSignals(True)
                self.occurrence.clear()
                self.occurrence.addItems(labels)
                self.occurrence.setCurrentIndex(min(index, len(candidates) - 1))
                self.occurrence.blockSignals(False)
            self.occurrence.setVisible(len(candidates) == 2)
            self.target = candidates[self.occurrence.currentIndex()]
            remaining = epoch_ns(self.target) - time_ns()
            self.resolved.setText(
                self.target.strftime("%a, %b %d, %Y · %H:%M:%S.")
                + f"{self.target.microsecond // 1000:03} {self.target:%Z (UTC%z)}"
            )
            self.countdown.setText(relative_text(remaining))
            self.error.setText("Choose a future time." if remaining <= 0 else "")
            self.submit.setEnabled(remaining > 0)
        except ValueError as exc:
            self.target = None
            self.resolved.setText("")
            self.countdown.setText("—")
            self.error.setText(str(exc))
            self.occurrence.hide()
            self.submit.setEnabled(False)

    def arm(self) -> None:
        self.refresh()
        if self.target is not None and self.submit.isEnabled():
            self.timer.stop()
            self.scheduled.emit(self.target)


class Completion(QObject):
    finished = Signal()
    failed = Signal(str)


class Autoclicker(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app = app
        self.overlays: list[CaptureOverlay] = []
        self.dialog: ScheduleDialog | None = None
        self.job: ScheduledClick | None = None
        self.tray: QSystemTrayIcon | None = None
        self.exit_code = 0
        self.completion = Completion()
        self.completion.finished.connect(self.done)
        self.completion.failed.connect(self.failed)
        self.app.aboutToQuit.connect(self.cancel)

    def select(self) -> None:
        for screen in self.app.screens():
            overlay = CaptureOverlay(screen)
            overlay.selected.connect(self.picked)
            overlay.cancelled.connect(self.app.quit)
            # Realize and configure the native window before making it visible.
            macos.prepare_overlay(overlay)
            overlay.show()
            self.overlays.append(overlay)
        if self.overlays:
            self.overlays[0].activateWindow()
            self.overlays[0].setFocus()

    def picked(self, point: QPoint, clicked_at: datetime) -> None:
        for overlay in self.overlays:
            overlay.hide()
            overlay.deleteLater()
        self.overlays.clear()
        self.dialog = ScheduleDialog(point, clicked_at)
        self.dialog.scheduled.connect(self.arm)
        self.dialog.rejected.connect(self.app.quit)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def arm(self, target: datetime) -> None:
        assert self.dialog is not None
        point = self.dialog.point
        try:
            click = macos.prepare_click(point.x(), point.y())
        except RuntimeError as exc:
            self.failed(str(exc))
            return
        # Hide before starting the worker. No scheduler window can intercept the click.
        self.dialog.hide()
        self.make_tray(target)
        self.job = ScheduledClick(
            epoch_ns(target),
            click,
            self.completion.finished.emit,
            self.completion.failed.emit,
        )
        print(
            f"Scheduled one click at ({point.x()}, {point.y()}) for "
            f"{target.isoformat(timespec='milliseconds')}. Cancel in the menu bar or with Ctrl+C.",
            flush=True,
        )
        self.job.start()

    def make_tray(self, target: datetime) -> None:
        pixmap = QPixmap(22, 22)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.GlobalColor.black)
        painter.drawEllipse(4, 4, 14, 14)
        painter.drawLine(11, 6, 11, 11)
        painter.drawLine(11, 11, 15, 13)
        painter.end()
        icon = QIcon(pixmap)
        icon.setIsMask(True)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("Autoclicker · one click scheduled")
        menu = QMenu()
        menu.addAction(
            target.strftime("Click at %b %d · %H:%M:%S.") + f"{target.microsecond // 1000:03}"
        ).setEnabled(False)
        self.tray_countdown = menu.addAction("")
        self.tray_countdown.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Cancel and quit", self.app.quit)
        self.tray.setContextMenu(menu)
        self.tray_menu = menu
        self.tray_timer = QTimer(self)
        self.tray_timer.timeout.connect(
            lambda: self.tray_countdown.setText(relative_text(epoch_ns(target) - time_ns()))
        )
        self.tray_timer.start(50)
        self.tray.show()

    def cancel(self) -> None:
        if self.job is not None:
            self.job.cancel()
            self.job.join(timeout=1)
        if self.tray is not None:
            self.tray.hide()

    def done(self) -> None:
        print("Clicked once. Done.", flush=True)
        self.app.quit()

    def failed(self, message: str) -> None:
        self.exit_code = 1
        QMessageBox.critical(None, "Could not schedule click", message)
        self.app.quit()


def main() -> int:
    try:
        macos.check_platform()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    app = QApplication(sys.argv)
    app.setApplicationName("Autoclicker")
    app.setQuitOnLastWindowClosed(False)
    if not macos.can_click(prompt=True):
        QMessageBox.information(
            None,
            "Allow Accessibility access",
            "Enable your terminal app (or Python, if listed) in System Settings → "
            "Privacy & Security → Accessibility, then run this command again.\n\n"
            "macOS requires this permission to send the scheduled click.",
        )
        return 1
    controller = Autoclicker(app)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    # Let Python handle Ctrl+C even while Qt's native event loop is idle.
    interrupt_timer = QTimer()
    interrupt_timer.timeout.connect(lambda: None)
    interrupt_timer.start(100)
    controller.select()
    app.exec()
    return controller.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
