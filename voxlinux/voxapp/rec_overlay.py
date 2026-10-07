"""Floating recording indicator for Vox (Wayland/Hyprland).

Borderless always-on-top pill with a live animation: pulsing red dot,
expanding rings and an elapsed-time counter, drawn with cairo at ~30 fps.
Runs as its own process so it never blocks the daemon:

    python3 rec_overlay.py        # show, runs until killed
    python3 rec_overlay.py --once # single frame smoke test (CI)

Killed by RecIndicator via terminate() on stop.
"""

from __future__ import annotations

import math
import sys
import time

try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk
    import cairo
except ImportError:
    print("rec_overlay: needs Gtk3 + cairo (python-gobject, python-cairo)",
          file=sys.stderr)
    raise SystemExit(1)

W, H = 220, 64
FPS_MS = 33
DOT_R = 10.0


class Overlay(Gtk.Window):
    def __init__(self) -> None:
        super().__init__(type=Gtk.WindowType.POPUP)
        self.set_title("VOX-REC")  # matched by the Hyprland nofocus rule
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        # Never steal keyboard focus: behave like a notification, not a window.
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_app_paintable(True)
        self.set_default_size(W, H)
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        monitor = screen.get_primary_monitor()
        geo = screen.get_monitor_geometry(monitor)
        # top-right, notification style
        self.move(geo.x + geo.width - W - 24, geo.y + 36)
        self._t0 = time.monotonic()
        area = Gtk.DrawingArea()
        area.set_size_request(W, H)
        area.connect("draw", self._draw)
        self.add(area)
        self._area = area
        GLib.timeout_add(FPS_MS, self._tick)

    def _tick(self) -> bool:
        self._area.queue_draw()
        return True

    def _draw(self, _w, cr: cairo.Context) -> bool:
        t = time.monotonic() - self._t0
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        # pill background
        self._round_rect(cr, 0.5, 0.5, W - 1, H - 1, 18)
        cr.set_source_rgba(0.09, 0.09, 0.11, 0.92)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.14)
        cr.set_line_width(1.0)
        cr.stroke()
        cx, cy = 30.0, H / 2
        # expanding rings (two, phase-shifted)
        for phase in (0.0, 0.5):
            p = (t * 0.9 + phase) % 1.0
            cr.arc(cx, cy, DOT_R + p * 16.0, 0, 2 * math.pi)
            cr.set_source_rgba(1.0, 0.23, 0.23, 0.55 * (1.0 - p))
            cr.set_line_width(2.0)
            cr.stroke()
        # pulsing dot
        pulse = 0.75 + 0.25 * math.sin(t * 2 * math.pi * 1.6)
        cr.arc(cx, cy, DOT_R * pulse, 0, 2 * math.pi)
        cr.set_source_rgb(1.0, 0.24, 0.24)
        cr.fill()
        # glow
        cr.arc(cx, cy, DOT_R * pulse + 3, 0, 2 * math.pi)
        cr.set_source_rgba(1.0, 0.24, 0.24, 0.25)
        cr.set_line_width(3.0)
        cr.stroke()
        # "REC" label
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL,
                            cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(17)
        cr.set_source_rgb(1, 1, 1)
        cr.move_to(56, 30)
        cr.show_text("REC")
        # elapsed timer, tabular-ish
        secs = int(t)
        cr.set_font_size(14)
        cr.set_source_rgba(1, 1, 1, 0.75)
        cr.move_to(56, 50)
        cr.show_text(f"{secs // 60:02d}:{secs % 60:02d}  •  идёт запись")
        return False

    @staticmethod
    def _round_rect(cr: cairo.Context, x, y, w, h, r) -> None:
        cr.move_to(x + r, y)
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()


def main(argv: list[str]) -> int:
    if "--once" in argv:  # headless smoke test: draw one frame to PNG
        inst = Overlay.__new__(Overlay)
        inst._t0 = time.monotonic() - 1.7  # fixed pose: mid-pulse, 00:01
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
        Overlay._draw(inst, None, cairo.Context(surf))
        surf.write_to_png("/tmp/vox_rec_once.png")
        print("wrote /tmp/vox_rec_once.png")
        return 0
    win = Overlay()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
