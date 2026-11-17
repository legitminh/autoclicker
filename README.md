# Autoclicker

A small **macOS** Python app that captures a point, schedules **one left click** in your local time zone, and quits. Managed with [uv](https://docs.astral.sh/uv/).

## Run

```sh
uv run autoclicker
```

Or run `uv run main.py` / `uv run python -m autoclicker` from this repository. uv installs Python 3.12 and the locked dependencies automatically.

1. **Pick a point.** A dimmed overlay covers each display. Click anywhere on it to record that position. The overlay consumes the press and release, so the selection does not activate the control underneath. Press **Esc** to cancel.
2. **Set the local date and time.** The popup defaults to the selection time rounded to the nearest minute; ties round forward. Edit **Days → Hour → Minute → Second → Millisecond** with **Tab** / **Shift+Tab**. Hours use the 24-hour clock; milliseconds range from 000 to 999.
3. **Schedule click.** The popup disappears, leaving a small clock icon in the macOS menu bar. At the selected instant, the pointer moves to the recorded coordinates, one left-click press/release pair is posted, and the app exits.

**Days** means calendar days after the date printed below the fields (the date you selected the point), from **0 to 9999**. For example, `Days: 2, Hour: 09, Minute: 30` means 9:30 a.m. two calendar dates later. The date anchor stays fixed if midnight passes while editing. The popup shows the full resolved date, time-zone offset, and a countdown that updates as you type and as time passes.

The nearest-minute default can be in the past. In that case, change it to a future time before scheduling. Times skipped by daylight saving are rejected. For a repeated hour, choose the earlier or later occurrence explicitly.

## macOS permission

On first run, allow your terminal application (Terminal, iTerm, Codex, etc.) or Python, whichever macOS lists, in **System Settings → Privacy & Security → Accessibility**. Then rerun the command. The app checks this permission before selection and before sending the click. Screen Recording and Input Monitoring permissions are not needed.

Cancel before selection or in the popup with **Esc**. Once armed, use the menu-bar clock → **Cancel and quit**, or **Ctrl+C** in the terminal.

## Timing and coordinates

- Millisecond input is supported; actual dispatch precision depends on macOS scheduling and system load. This is not a hard real-time tool.
- Keep the Mac awake and unlocked until the click. If it sleeps across the deadline, the click is dispatched when the process resumes. Clock corrections are followed because this schedules a wall-clock instant.
- The time zone is detected from your system when the point is selected. The chosen instant stays fixed if your system time zone changes later.
- Coordinates use macOS global screen points, including Retina and negative-coordinate displays. Keep the target window and display arrangement in place. The app clicks that coordinate in whichever application is underneath at execution time.
- The capture overlay supports multiple displays and full-screen application Spaces. Secure macOS system surfaces may take precedence over ordinary application windows.

## Development

```sh
uv sync --dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv build
```

Tests cover calendar calculations, DST transitions, millisecond values, countdown updates, Tab navigation, release-before-selection behavior, one-shot scheduling, and cancellation. GUI tests run offscreen and do not inject real clicks.

For an opt-in native end-to-end check, run `uv run python scripts/native_smoke.py`. It opens its own test button, sends a selection click that must be swallowed, schedules a click about one second later, and verifies the button receives exactly one click. Leave the pointer alone while it runs; Accessibility permission is required.

Python 3.12+, Qt for Python Essentials, tzlocal, and PyObjC are used. Native Quartz handles the final click; Qt provides the capture overlays and popup. The app currently supports macOS only.

## License

MIT — see [LICENSE](LICENSE).
