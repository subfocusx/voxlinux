"""
Vox dictation daemon for Linux (Wayland + Hyprland).

One long-lived process that owns the microphone and the control socket:

    Hyprland bind ──▶ vox-ptt start / stop
                            │  (unix socket in $XDG_RUNTIME_DIR)
                            ▼
    stop ──▶ PushToTalkMic.stop() ──▶ engines.transcribe()
                                      ──▶ PostProcessor.process()
                                      ──▶ platform_linux.type_text()

The recognizer is loaded lazily on the first capture, so service start is
instant and `systemctl --user start voxlinux` never blocks on a 160 MB model.
Latency from key release to text insertion is printed and notified, because
that is the number users actually care about.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any

from voxapp import platform_linux as plat
from voxapp.config import MIN_RECORD_MS, ENABLE_BEEPS, load_config
from voxapp.engines import build_engine
from voxapp.post_processor import PostProcessor
from voxapp.registry import DEFAULT_MODEL_ID, MODELS, is_installed


DEFAULT_MAX_SECONDS = 120.0
"""Hard cap on one dictation hold, so a forgotten key cannot record forever."""


class DictationDaemon:
    """
    Owns the mic, the recognizer and the control socket.

    Capture runs in the socket thread; recognition + insertion run on a worker
    thread, so a `vox-ptt stop` issued while a previous dictation is still
    being recognised is answered immediately instead of blocking the bind.
    """

    def __init__(
        self,
        *,
        model_id: str | None = None,
        min_record_ms: int = MIN_RECORD_MS,
        max_seconds: float = DEFAULT_MAX_SECONDS,
        auto_paste: bool = True,
        beeps: bool = ENABLE_BEEPS,
    ) -> None:
        self.model_id = model_id or load_config().get("model") or DEFAULT_MODEL_ID
        self.min_record_ms = min_record_ms
        self.max_seconds = max_seconds
        self.auto_paste = auto_paste
        self.beeps = beeps

        self.mic = plat.PushToTalkMic()
        self.rec_indicator = plat.RecIndicator()
        self.control = plat.ControlServer(
            self.mic, on_start=self.start_recording, on_stop=self.stop_recording
        )
        self._engine: Any = None
        self._engine_lock = threading.Lock()
        self._busy = threading.Lock()
        self._stopped = threading.Event()

        plat.set_beeps(beeps)

    # -- recognizer ------------------------------------------------------
    def engine(self):
        """Load the model on first use; cached afterwards."""
        with self._engine_lock:
            if self._engine is None:
                if not is_installed(self.model_id):
                    raise RuntimeError(
                        f"model {self.model_id!r} is not installed "
                        f"(expected {MODELS[self.model_id]['extracted_dir']})"
                    )
                self._engine = build_engine(self.model_id)
            return self._engine

    # -- capture plumbing ------------------------------------------------
    def start_recording(self) -> str:
        """Begin a hold. Returns the control-socket reply."""
        if self.mic.is_recording:
            return "already recording\n"
        self.mic.start()
        plat.beep("start")
        self.rec_indicator.start()
        self.control.arm_timeout(self.max_seconds)
        return "recording\n"

    def stop_recording(self) -> str:
        """End the hold and hand the PCM to a worker thread."""
        self.control.disarm_timeout()
        pcm = self.mic.stop()
        self.rec_indicator.stop()
        plat.beep("stop")
        if pcm is None or self.mic.duration_ms() < self.min_record_ms:
            return "ignored (too short or silent)\n"
        threading.Thread(
            target=self._run_pipeline, args=(pcm,), name="vox-pipeline", daemon=True
        ).start()
        return "processing\n"

    # -- pipeline --------------------------------------------------------
    def _run_pipeline(self, pcm) -> None:
        if not self._busy.acquire(blocking=False):
            print("[VOX] previous dictation still running — capture dropped", flush=True)
            return
        try:
            t_release = time.perf_counter()
            duration = pcm.size / plat.SAMPLE_RATE

            raw = self.engine().transcribe(pcm).strip()
            t_stt = time.perf_counter()

            info = MODELS[self.model_id]
            pp = PostProcessor.from_model_config(info)
            text = pp.process(raw).processed.strip()
            t_post = time.perf_counter()

            if not text:
                print("[VOX] nothing recognised", flush=True)
                plat.notify("Ничего не распознано", urgency="low")
                return

            rc = plat.type_text(text) if self.auto_paste else 0
            t_paste = time.perf_counter()

            if rc != 0:
                plat.notify(f"Не удалось вставить текст (wtype rc={rc})", urgency="critical")
                return

            total_ms = (t_paste - t_release) * 1000.0
            print(
                f"[VOX] {duration:.1f}s audio | raw: {raw!r}\n"
                f"[VOX] text: {text!r}\n"
                f"[VOX] stt {t_stt - t_release:.2f}s | post {t_post - t_stt:.2f}s | "
                f"paste {t_paste - t_post:.2f}s | release→insert {total_ms:.0f} ms",
                flush=True,
            )
            plat.notify(f"{text}  ({total_ms:.0f} мс)", urgency="low")
        except Exception as exc:  # a bad capture must never kill the daemon
            print(f"[VOX] pipeline failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            plat.notify(f"Ошибка: {exc}", urgency="critical")
        finally:
            self._busy.release()

    # -- lifecycle -------------------------------------------------------
    def run_forever(self) -> None:
        print(
            f"[VOX] daemon starting (model={self.model_id}, "
            f"socket={self.control.path})",
            flush=True,
        )
        blockers = plat.Tools.missing_blockers()
        if blockers:
            print(f"[VOX] missing tools: {', '.join(blockers)}", file=sys.stderr, flush=True)
        try:
            self.control.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self._stopped.set()
            self.mic.close()
            print("[VOX] daemon stopped", flush=True)

    def shutdown(self) -> None:
        self._stopped.set()
        self.mic.close()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in plat.ControlServer.COMMANDS:
        print(plat.send_control(" ".join(argv)))
        return 0

    model_id = argv[0] if argv else None
    daemon = DictationDaemon(model_id=model_id)
    daemon.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())