"""
Linux (Wayland + Hyprland) platform layer for Vox.

Replaces the Windows pieces of upstream `worker.py`:

* microphone capture — sounddevice InputStream, 16 kHz / mono / int16,
  exactly what sherpa-onnx (GigaAM v3) wants;
* push-to-talk hotkey — evdev `KEY_RCTRL` hold (needs no compositor config),
  with a Hyprland-bind fallback that polls the compositor for the held key;
* text insertion — `wtype` (virtual keyboard protocol);
* notifications — `notify-send`;
* beeps — `paplay` on a generated WAV; disableable.

Nothing here is Windows-specific and nothing here talks to the recognizer: the
module only moves bytes (audio in, keystrokes out) and exposes state changes.
"""

from __future__ import annotations

import contextlib
import errno
import math
import os
import queue
import select
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave
from shutil import which
from typing import Iterator

import numpy as np

from voxapp.config import SAMPLE_RATE, get_cache_dir

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BLOCK_SIZE = 4000
"""PortAudio frames per callback (250 ms @ 16 kHz)."""

APP_NAME = "Vox"
DEFAULT_PTT_KEY = "KEY_RCTRL"
"""evdev name of the hold-to-talk key (right Ctrl), the upstream default."""

HYPRLAND_KEY = "Right"
"""
X keysym for right Ctrl, which is what Hyprland binds and `hl.is_key_down`
call it. The evdev name above (`KEY_RCTRL`) and the Hyprland name differ, and
the keysym is case-sensitive — do not lower-case it.
"""

CONTROL_SOCKET = "voxlinux.sock"
"""Name of the control socket inside $XDG_RUNTIME_DIR."""

KEY_STATE_POLL_S = 0.02
"""Poll interval when detecting hotkey hold via the compositor."""

BEEP_FREQS = {"start": 880.0, "stop": 440.0}
BEEP_MS = 80


# ---------------------------------------------------------------------------
# External tool discovery
# ---------------------------------------------------------------------------




class Tools:
    """Resolved paths to the external helpers, resolved once at import."""

    wtype: str | None = None
    notify_send: str | None = None
    paplay: str | None = None
    hyprctl: str | None = None

    @classmethod
    def detect(cls) -> dict[str, str | None]:
        cls.wtype = which("wtype")
        cls.notify_send = which("notify-send")
        cls.paplay = which("paplay")
        cls.hyprctl = which("hyprctl")
        return {
            "wtype": cls.wtype,
            "notify-send": cls.notify_send,
            "paplay": cls.paplay,
            "hyprctl": cls.hyprctl,
        }

    @classmethod
    def missing_blockers(cls) -> list[str]:
        """Packages that must be installed for a working dictation loop."""
        pkgs = {
            "wtype": "wtype",
            "notify-send": "libnotify",
            "paplay": "pipewire-pulse (paplay)",
            "hyprctl": "hyprland",
        }
        return [pkgs[name] for name, path in (
            ("wtype", cls.wtype),
            ("notify-send", cls.notify_send),
            ("paplay", cls.paplay),
            ("hyprctl", cls.hyprctl),
        ) if not path]


Tools.detect()


# ---------------------------------------------------------------------------
# Text insertion / notifications / beeps
# ---------------------------------------------------------------------------


def type_text(text: str) -> int:
    """
    Insert `text` at the cursor of the focused Wayland client.

    Primary path: clipboard + Shift+Insert (`wl-copy` + `wtype -M shift
    -P Insert -m shift`). One atomic paste — Chrome omnibox and other
    single-line inputs keep focus, unlike per-key `wtype -- <text>` typing
    which trips their autocomplete/filter on every keystroke.
    Fallback: direct `wtype -- <text>` when wl-copy/wtype are missing.
    Returns 0 on success, nonzero otherwise.
    """
    if not text:
        return 0
    wl_copy = which("wl-copy")
    if wl_copy and Tools.wtype:
        try:
            subprocess.Popen(
                [wl_copy],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
            ).communicate(input=text, timeout=5)
            paste = subprocess.run(
                [Tools.wtype, "-M", "shift", "-P", "Insert", "-m", "shift"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if paste.returncode == 0:
                return 0
            print(
                f"[PLATFORM] wtype paste rc={paste.returncode}: "
                f"{paste.stderr.strip()}",
                file=sys.stderr,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"[PLATFORM] clipboard paste failed: {exc}", file=sys.stderr)
    if not Tools.wtype:
        print("[PLATFORM] wtype not found — cannot insert text", file=sys.stderr)
        return -1
    try:
        proc = subprocess.run(
            [Tools.wtype, "--", text],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"[PLATFORM] wtype failed: {exc}", file=sys.stderr)
        return -1
    if proc.returncode != 0:
        print(
            f"[PLATFORM] wtype rc={proc.returncode}: {proc.stderr.strip()}",
            file=sys.stderr,
        )
    return proc.returncode


def notify(message: str, *, title: str = APP_NAME, urgency: str = "normal") -> bool:
    """Show a desktop notification through notify-send."""
    if not Tools.notify_send:
        print(f"[NOTIFY] {title}: {message}")
        return False
    try:
        proc = subprocess.run(
            [Tools.notify_send, "--app-name", title, "--urgency", urgency, message],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"[PLATFORM] notify-send failed: {exc}", file=sys.stderr)
        return False
    return proc.returncode == 0


class RecIndicator:
    """
    Floating animated recording indicator.

    Spawns `rec_overlay.py` — a borderless always-on-top pill with a pulsing
    red dot, expanding rings and an elapsed timer, drawn with cairo at 30 fps.
    Positioned bottom-center via a Hyprland window rule (see vox-bindings.lua
    in ~/.config/hypr). `start()` is idempotent, `stop()` kills the process
    and is a silent no-op when idle.
    """

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        with self._lock:
            if self.active:
                return
            overlay = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "rec_overlay.py")
            # NOTE: system python — Gtk/cairo есть только вне venv.
            py = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
            try:
                self._proc = subprocess.Popen(
                    [py, overlay],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except OSError as exc:
                print(f"[PLATFORM] rec overlay failed: {exc}", file=sys.stderr)
                self._proc = None

    def stop(self) -> None:
        with self._lock:
            proc, self._proc = self._proc, None
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()


_beeps_enabled = True
_beep_files: dict[str, str] = {}


def set_beeps(enabled: bool) -> None:
    """Globally enable/disable the record/stop tones."""
    global _beeps_enabled
    _beeps_enabled = enabled


def _beep_wav(kind: str) -> str | None:
    """Generate (once) a short sine WAV for `kind` and return its path."""
    if kind in _beep_files:
        return _beep_files[kind]
    freq = BEEP_FREQS.get(kind)
    if freq is None:
        return None
    n = int(SAMPLE_RATE * BEEP_MS / 1000)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    # Fade the edges: a raw square-ish click pops on cheap speakers.
    env = np.hanning(n) if n > 2 else np.ones(n)
    pcm = (np.sin(2 * math.pi * freq * t) * env * 12000).astype("<i2")
    path = os.path.join(get_cache_dir(), f"beep-{kind}.wav")
    try:
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(pcm.tobytes())
    except (OSError, struct.error):
        return None
    _beep_files[kind] = path
    return path


def beep(kind: str = "start") -> bool:
    """Play the `start`/`stop` tone. No-op when beeps are disabled."""
    if not _beeps_enabled or not Tools.paplay:
        return False
    path = _beep_wav(kind)
    if path is None:
        return False
    try:
        subprocess.Popen(
            [Tools.paplay, path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# Microphone capture
# ---------------------------------------------------------------------------


class PushToTalkMic:
    """
    16 kHz mono int16 microphone, captured in fixed-size blocks.

    Mirrors the upstream `sd.InputStream` callback: `start()` marks the stream
    as recording and the callback queues every block; `stop()` closes the
    stream and `frames()` hands back the concatenated int16 buffer.
    """

    def __init__(self, samplerate: int = SAMPLE_RATE, blocksize: int = BLOCK_SIZE):
        self.samplerate = samplerate
        self.blocksize = blocksize
        self._chunks: queue.Queue[np.ndarray] = queue.Queue()
        self._stream = None
        self._recording = False
        self._stopped_at = 0.0
        self._started_at = 0.0

    # -- state ----------------------------------------------------------
    @property
    def is_recording(self) -> bool:
        return self._recording

    def duration_ms(self) -> float:
        """Length of the current (or just finished) hold, in milliseconds."""
        end = time.monotonic() if self._recording else self._stopped_at
        return (end - self._started_at) * 1000.0 if self._started_at else 0.0

    # -- lifecycle ------------------------------------------------------
    def open(self) -> None:
        """Open the PortAudio stream. Raises on a missing/blocked device."""
        import sounddevice as sd  # imported late: heavy, optional at import time

        self._stream = sd.InputStream(
            samplerate=self.samplerate,
            blocksize=self.blocksize,
            dtype="int16",
            channels=1,
            callback=self._callback,
        )
        self._stream.start()

    def close(self) -> None:
        if self._stream is not None:
            with contextlib.suppress(Exception):
                self._stream.stop()
            with contextlib.suppress(Exception):
                self._stream.close()
            self._stream = None

    def start(self) -> None:
        """Begin recording. The stream is (re)opened if needed."""
        if self._recording:
            return
        self._drain()
        if self._stream is None:
            self.open()
        self._recording = True
        self._started_at = time.monotonic()

    def stop(self) -> np.ndarray | None:
        """
        Stop recording and return the captured PCM, or None if it was too
        short / silent to be worth recognising.
        """
        if not self._recording:
            return None
        self._recording = False
        self._stopped_at = time.monotonic()
        pcm = self._drain()
        if pcm is None or pcm.size == 0:
            return None
        if int(np.max(np.abs(pcm))) < 100:
            return None
        return pcm

    def __enter__(self) -> "PushToTalkMic":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self._recording = False
        self.close()

    # -- internals ------------------------------------------------------
    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            print(f"[AUDIO] {status}", file=sys.stderr)
        if self._recording:
            self._chunks.put(indata.copy())

    def _drain(self) -> np.ndarray | None:
        chunks = []
        while True:
            try:
                chunks.append(self._chunks.get_nowait())
            except queue.Empty:
                break
        if not chunks:
            return None
        return np.concatenate(chunks).flatten().astype(np.int16, copy=False)


def record_push_to_talk(
    events: Iterator[bool] | None = None,
    *,
    minimum_ms: int = 250,
    max_seconds: float = 120.0,
) -> np.ndarray | None:
    """
    One blocking push-to-talk capture: wait for the hotkey, record while it
    is held, return the int16 PCM on release. Returns None when the hold was
    shorter than `minimum_ms` or the mic heard nothing.

    `events` is a stream of press states (see `ptt_events`); when omitted the
    default hotkey source is used.
    """
    mic = PushToTalkMic()
    if events is None:
        events = ptt_events()
    for pressed in events:
        if not pressed:
            continue
        mic.start()
        beep("start")
        deadline = time.monotonic() + max_seconds
        for released in events:
            if not released or time.monotonic() >= deadline:
                break
        pcm = mic.stop()
        beep("stop")
        if pcm is None or mic.duration_ms() < minimum_ms:
            return None
        return pcm
    return None


# ---------------------------------------------------------------------------
# Hotkey detection — evdev (primary)
# ---------------------------------------------------------------------------

KEY_RCTRL_CODE = 97


def _evdev_available() -> bool:
    try:
        import evdev  # noqa: F401
    except ImportError:
        return False
    return os.path.isdir("/dev/input")


def _keyboard_devices() -> list[str]:
    """Event nodes of devices that expose EV_KEY, skipping our own grabs."""
    import evdev

    out = []
    for path in sorted(os.listdir("/dev/input")):
        if not path.startswith("event"):
            continue
        node = os.path.join("/dev/input", path)
        try:
            dev = evdev.InputDevice(node)
            ec = dev.capabilities()
            dev.close()
        except (OSError, PermissionError):
            continue
        if evdev.ecodes.EV_KEY in ec:
            out.append(node)
    return out


def evdev_ptt_events(key_code: int = KEY_RCTRL_CODE) -> Iterator[bool]:
    """
    Yield True when the push-to-talk key goes down and False on release.

    Requires read access to /dev/input/event* (group `input` or an udev rule);
    without it Hyprland's `hyprctl` key-state poll is used instead.
    """
    import evdev

    selector = select.epoll()
    fds: dict[int, str] = {}
    for node in _keyboard_devices():
        try:
            fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EPERM):
                print(f"[PTT] no permission to read {node}", file=sys.stderr)
            continue
        selector.register(fd, select.EPOLLIN)
        fds[fd] = node

    if not fds:
        raise PermissionError("no readable /dev/input event devices")

    pressed = False
    try:
        while True:
            for fd, _event in selector.poll():
                try:
                    dev_ev = evdev.InputDevice.from_fd(fd)
                    for event in dev_ev.read():
                        if event.type != evdev.ecodes.EV_KEY or event.code != key_code:
                            continue
                        now_pressed = event.value in (1, 2)  # 1 down, 2 auto-repeat
                        if now_pressed != pressed:
                            pressed = now_pressed
                            yield pressed
                except OSError:
                    continue
    finally:
        for fd in fds:
            with contextlib.suppress(OSError):
                os.close(fd)
        selector.close()


# ---------------------------------------------------------------------------
# Hotkey detection — Hyprland key-state poll (fallback)
# ---------------------------------------------------------------------------


def hyprland_key_is_down(key: str = HYPRLAND_KEY) -> bool:
    """
    Ask Hyprland whether `key` is currently held, via the Lua REPL's
    `hl.is_key_down`. (`hyprctl eval` rejects a bare `if ... end` expression,
    and echoes the code back on error, which would fake a positive result.)

    `key` is an X keysym and is case-sensitive (`Right`, not `right`).
    """
    if not Tools.hyprctl:
        return False
    code = f'if hl.is_key_down("{key}") then return "DOWN" else return "UP" end'
    try:
        proc = subprocess.run(
            [Tools.hyprctl, "repl"],
            input=code + "\n",
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    # The REPL echoes the submitted line and prints its own "> " prompt
    # afterwards, so the value is the last line that is neither.
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if line and not line.startswith(">"):
            return line == "DOWN"
    return False


def hyprland_ptt_events(key: str = HYPRLAND_KEY) -> Iterator[bool]:
    """
    Emulate hold-to-talk without /dev/input access: a Hyprland bind holds a
    modifier (or presses a key) and execs us; this loop then follows the
    key's own state and yields down/True on release False.
    """
    pressed = False
    while True:
        now = hyprland_key_is_down(key)
        if now != pressed:
            pressed = now
            yield pressed
        time.sleep(KEY_STATE_POLL_S)


def ptt_events() -> Iterator[bool]:
    """
    Preferred hotkey source: evdev when /dev/input is readable, compositor
    key-state poll otherwise. Yields True on press, False on release.
    """
    if _evdev_available():
        try:
            yield from evdev_ptt_events()
            return
        except (PermissionError, OSError, ImportError) as exc:
            print(f"[PTT] evdev unavailable ({exc}); using Hyprland poll", file=sys.stderr)
    if Tools.hyprctl:
        yield from hyprland_ptt_events(HYPRLAND_KEY)
        return
    raise RuntimeError("no hotkey source: need /dev/input access or hyprctl")


# ---------------------------------------------------------------------------
# Control socket (Hyprland-bind / CLI mode)
# ---------------------------------------------------------------------------


def socket_path() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return os.path.join(runtime, CONTROL_SOCKET)


class ControlServer:
    """
    Unix-socket command channel for `start` / `stop` / `toggle` / `hold KEY`.

    This is what `hyprland-bind.conf.example` and `scripts/vox-ptt` talk to;
    the running worker owns the socket and the microphone.
    """

    COMMANDS = ("start", "stop", "toggle", "hold", "status", "ping")

    def __init__(
        self,
        mic: PushToTalkMic,
        path: str | None = None,
        *,
        on_start=None,
        on_stop=None,
    ):
        """
        `on_start` / `on_stop` are optional callbacks that fully own the
        start/stop verbs (the daemon passes them, so beeps, the hold timeout
        and recognition stay in the daemon). Without them the server drives
        the microphone itself.
        """
        self.mic = mic
        self.path = path or socket_path()
        self.on_start = on_start
        self.on_stop = on_stop
        self._sock: socket.socket | None = None
        self._timeout_timer: threading.Timer | None = None

    def arm_timeout(self, seconds: float) -> None:
        """Auto-stop a hold that outlives `seconds`, so a lost release event
        cannot record forever."""
        self.disarm_timeout()
        self._timeout_timer = threading.Timer(seconds, self._timeout_stop)
        self._timeout_timer.daemon = True
        self._timeout_timer.start()

    def disarm_timeout(self) -> None:
        if self._timeout_timer is not None:
            self._timeout_timer.cancel()
            self._timeout_timer = None

    def _timeout_stop(self) -> None:
        if not self.mic.is_recording:
            return
        print("[VOX] max hold reached — auto stop", file=sys.stderr, flush=True)
        if self.on_stop is not None:
            self.on_stop()
        else:
            self.mic.stop()

    def serve_forever(self) -> None:
        """Accept control commands until the process is stopped."""
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self.path)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.path)
        os.chmod(self.path, 0o600)
        srv.listen(8)
        self._sock = srv
        print(f"[CTRL] listening on {self.path}", flush=True)
        try:
            while True:
                conn, _ = srv.accept()
                with conn, contextlib.suppress(OSError):
                    cmd = conn.recv(256).decode("utf-8", "replace").strip()
                    try:
                        reply = self.handle(cmd)
                    except Exception as exc:  # one bad command must not kill the daemon
                        reply = f"error: {type(exc).__name__}: {exc}\n"
                        print(f"[CTRL] {reply.strip()}", file=sys.stderr, flush=True)
                    conn.sendall(reply.encode("utf-8"))
        finally:
            self.disarm_timeout()
            with contextlib.suppress(OSError):
                srv.close()
            with contextlib.suppress(FileNotFoundError):
                os.unlink(self.path)

    def handle(self, cmd: str) -> str:
        """
        Dispatch one control command.

        When `on_start`/`on_stop` are installed (the daemon does that), the
        whole verb handling is delegated to them, so beeps, the hold timeout
        and recognition all live in one place. Without them this falls back to
        driving the microphone directly.
        """
        verb, _, arg = cmd.partition(" ")
        verb = verb.strip().lower()
        arg = arg.strip()

        if verb in ("ping", ""):
            return "pong\n"
        if verb == "status":
            return ("recording\n" if self.mic.is_recording else "idle\n")
        if verb not in self.COMMANDS:
            return f"error: unknown command {verb!r}\n"

        if self.on_start is not None:
            if verb == "start":
                return self.on_start()
            if verb == "stop":
                return self.on_stop()
            if verb == "toggle":
                return self.on_stop() if self.mic.is_recording else self.on_start()
            key = arg or HYPRLAND_KEY
            self.on_start()
            while hyprland_key_is_down(key):
                time.sleep(KEY_STATE_POLL_S)
            return self.on_stop()

        self.disarm_timeout()
        if verb == "start":
            self.mic.start()
        elif verb == "stop":
            self.mic.stop()
        elif verb == "toggle":
            if self.mic.is_recording:
                self.mic.stop()
            else:
                self.mic.start()
        else:  # hold
            key = arg or HYPRLAND_KEY
            if hyprland_key_is_down(key):
                self.mic.start()
                while hyprland_key_is_down(key):
                    time.sleep(KEY_STATE_POLL_S)
                self.mic.stop()
        return ("recording\n" if self.mic.is_recording else "idle\n")


# ---------------------------------------------------------------------------
# Self-test entry point
# ---------------------------------------------------------------------------


def send_control(command: str, path: str | None = None, timeout: float = 10.0) -> str:
    """Send one command to a running ControlServer and return its reply."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(path or socket_path())
        sock.sendall(command.encode("utf-8"))
        return sock.recv(256).decode("utf-8", "replace").strip()


def main(argv: list[str] | None = None) -> int:
    """
    Platform smoke test: report tool availability, then type a marker into the
    focused window and raise a notification. Used by scripts/test_platform.py.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ControlServer.COMMANDS:
        print(send_control(" ".join(argv)))
        return 0

    marker = argv[0] if argv else f"Vox wtype OK {time.strftime('%H:%M:%S')}"

    found = Tools.detect()
    print("[PLATFORM] tools:")
    for name, path in found.items():
        print(f"  {'OK  ' if path else 'MISS'} {name}: {path or '<not installed>'}")
    blockers = Tools.missing_blockers()
    if blockers:
        print("[PLATFORM] install blockers: " + ", ".join(blockers), file=sys.stderr)

    print(f"[PLATFORM] typing marker: {marker}")
    rc = type_text(marker)
    print(f"[PLATFORM] wtype returncode: {rc}")

    print("[PLATFORM] sending notification")
    notify_rc = notify(f"wtype rc={rc}: {marker}")
    print(f"[PLATFORM] notify-send returncode: {0 if notify_rc else 1}")

    beep("start")
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())