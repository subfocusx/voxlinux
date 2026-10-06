#!/usr/bin/env python3
"""
Platform smoke test: prove the Wayland insertion path works.

Types a marker into the window that currently has focus (via `wtype`) and
raises a notification, printing both tools' return codes so the run is
self-verifying.

Usage:
    python3 scripts/test_platform.py ["текст для вставки"]
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from voxapp import platform_linux as plat  # noqa: E402


def main() -> int:
    marker = sys.argv[1] if len(sys.argv) > 1 else (
        f"Vox platform OK {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    tools = plat.Tools.detect()
    print("=== tools ===")
    for name, path in tools.items():
        print(f"  {'OK  ' if path else 'MISS'}  {name:12s} {path or '<not installed>'}")
    blockers = plat.Tools.missing_blockers()
    if blockers:
        print(f"  ! install blockers: {', '.join(blockers)}")

    print(f"\n=== typing into the focused window: {marker!r}")
    rc = plat.type_text(marker)
    print(f"  wtype returncode: {rc} ({'inserted' if rc == 0 else 'FAILED'})")

    print("\n=== notification")
    sent = plat.notify(f"wtype rc={rc}: {marker}")
    print(f"  notify-send returncode: {0 if sent else 1}")

    print("\n=== beep")
    print(f"  paplay tone: {'played' if plat.beep('start') else 'skipped'}")

    if rc == 0:
        print("\nPASS: text was inserted into the focused window")
        return 0
    print("\nFAIL: wtype did not insert the text")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())