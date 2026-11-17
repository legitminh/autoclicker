"""Native macOS window placement, permission checks, and a single Quartz click."""

import sys
from collections.abc import Callable


def check_platform() -> None:
    if sys.platform != "darwin":
        raise RuntimeError("This autoclicker currently supports macOS only.")


def can_click(*, prompt: bool = False) -> bool:
    import ApplicationServices

    if prompt:
        return bool(
            ApplicationServices.AXIsProcessTrustedWithOptions(
                {ApplicationServices.kAXTrustedCheckOptionPrompt: True}
            )
        )
    return bool(ApplicationServices.AXIsProcessTrusted())


def prepare_overlay(widget) -> None:
    import AppKit
    import objc

    # Qt's native handle on macOS is an NSView. Keep the capture surface above
    # ordinary windows, the menu bar, the Dock, and full-screen application spaces.
    view = objc.objc_object(c_void_p=int(widget.winId()))
    window = view.window()
    window.setLevel_(AppKit.NSScreenSaverWindowLevel)
    window.setCollectionBehavior_(
        AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
        | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
    )
    window.setHidesOnDeactivate_(False)
    window.setIgnoresMouseEvents_(False)


def prepare_click(x: int, y: int) -> Callable[[], None]:
    """Allocate the pair before the deadline; leave only dispatch for the worker."""
    import Quartz

    if not can_click():
        raise RuntimeError("Accessibility permission was removed. Grant it and run again.")
    source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStatePrivate)
    if source is None:
        raise RuntimeError("macOS could not create a mouse event source.")
    events = [
        Quartz.CGEventCreateMouseEvent(source, kind, (x, y), Quartz.kCGMouseButtonLeft)
        for kind in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp)
    ]
    if any(event is None for event in events):
        raise RuntimeError("macOS could not create the click events.")
    for event in events:
        Quartz.CGEventSetIntegerValueField(event, Quartz.kCGMouseEventClickState, 1)

    def dispatch() -> None:
        if not can_click():
            raise RuntimeError("Accessibility permission was removed. Grant it and run again.")
        Quartz.CGWarpMouseCursorPosition((x, y))
        for event in events:
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

    return dispatch


def single_click(x: int, y: int) -> None:
    prepare_click(x, y)()
