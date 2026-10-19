"""Silero VAD based speech segmentation for the VoxLinux dictation app.

Why this exists: the GigaAM v3 encoder has a hard input-length limit of
~200 s — a 201 s utterance crashes ONNX Runtime with
``"5000 by 5500"`` — and accuracy/latency degrade on long single-shot
decodes. So before decoding we cut the dictation into short speech-only
segments (<= ``max_speech_seconds``, default 20 s) and decode each one
independently. Silence between segments is dropped.

Back end: ``sherpa_onnx.VoiceActivityDetector`` with the Silero VAD
model (``silero_vad.onnx``). The app's internal PCM format is int16
mono at 16 kHz; :meth:`SpeechSegmenter.split` takes that format and
returns a list of int16 arrays in the same format.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import urllib.request
from collections.abc import Callable

import numpy as np

try:
    from voxapp.config import get_models_dir
except ImportError:  # direct script run: python voxapp/vad.py
    from config import get_models_dir  # type: ignore[no-redef]

VAD_MODEL_FILENAME = "silero_vad.onnx"
VAD_MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "asr-models/silero_vad.onnx"
)

_CHUNK = 256 * 1024  # 256 KiB


def vad_model_path() -> str:
    """Absolute path where silero_vad.onnx is expected (<models_dir>/silero_vad.onnx)."""
    return os.path.join(get_models_dir(), VAD_MODEL_FILENAME)


def is_available() -> bool:
    """True if the Silero model file exists on disk."""
    return os.path.isfile(vad_model_path())


class SpeechSegmenter:
    """Split int16 PCM into speech-only segments using Silero VAD."""

    def __init__(
        self,
        model_path: str | None = None,
        *,
        sample_rate: int = 16000,
        max_speech_seconds: float = 20.0,
        threshold: float = 0.5,
        min_silence_seconds: float = 0.25,
        min_speech_seconds: float = 0.25,
        num_threads: int = 1,
        pad_ms: float = 200.0,
    ) -> None:
        self.model_path = model_path or vad_model_path()
        self.sample_rate = sample_rate
        self.max_speech_seconds = max_speech_seconds
        self.threshold = threshold
        self.min_silence_seconds = min_silence_seconds
        self.min_speech_seconds = min_speech_seconds
        self.num_threads = num_threads
        # The detector reports speech a couple of windows late and stops a
        # couple of windows early, which clipped word onsets ("ничьих" came
        # out as "чьих"). Pad every span to restore the consonants.
        self.pad_samples = int(pad_ms * sample_rate / 1000.0)

    def split(self, pcm_int16: np.ndarray) -> list[np.ndarray]:
        """Split int16 PCM into speech-only segments (int16, same sample rate).

        Returns [] when the VAD model is unavailable or the audio contains
        no speech. Never raises for "model missing" — the caller falls
        back to single-shot decoding.
        """
        if pcm_int16 is None or len(pcm_int16) == 0:
            return []
        pcm = np.asarray(pcm_int16, dtype=np.int16)
        if pcm.size == 0:
            return []
        if not os.path.isfile(self.model_path):
            return []

        try:
            import sherpa_onnx
        except ImportError:
            return []

        try:
            config = sherpa_onnx.VadModelConfig()
            config.sample_rate = self.sample_rate
            config.num_threads = self.num_threads
            config.silero_vad.model = self.model_path
            config.silero_vad.threshold = self.threshold
            config.silero_vad.min_silence_duration = self.min_silence_seconds
            config.silero_vad.min_speech_duration = self.min_speech_seconds
            config.silero_vad.max_speech_duration = self.max_speech_seconds
            buffer_seconds = max(30.0, float(self.max_speech_seconds) + 5.0)
            vad = sherpa_onnx.VoiceActivityDetector(
                config, buffer_size_in_seconds=buffer_seconds
            )
            ws = int(config.silero_vad.window_size)

            samples = (pcm.astype(np.float32) / 32768.0).tolist()

            spans: list[tuple[int, int]] = []

            def _drain() -> None:
                while not vad.empty():
                    seg = vad.front
                    # NOTE: front returns a reference valid only until the
                    # next VAD call — copy start/length before pop().
                    start = int(seg.start)
                    length = len(seg.samples)
                    vad.pop()
                    if length > 0:
                        spans.append((start, start + length))

            # Feed window by window; a trailing partial window is fed as-is
            # (this also covers audio shorter than one VAD window).
            pos = 0
            total = len(samples)
            while pos + ws <= total:
                vad.accept_waveform(samples[pos : pos + ws])
                pos += ws
                _drain()
            if pos < total:
                vad.accept_waveform(samples[pos:])
                _drain()
            vad.flush()
            _drain()
        except Exception:
            return []

        n = int(pcm.size)
        # Clip to the input range, drop empties, keep original order,
        # and de-overlap defensively (VAD spans should not overlap).
        spans.sort(key=lambda s: s[0])

        # Pad every span and merge the ones that now touch: the padding
        # would otherwise make neighbours overlap, and decoding the same
        # audio twice would duplicate text.
        padded: list[tuple[int, int]] = []
        for start, end in spans:
            s = max(0, start - self.pad_samples)
            e = min(n, end + self.pad_samples)
            if e <= s:
                continue
            if padded and s <= padded[-1][1]:
                padded[-1] = (padded[-1][0], max(padded[-1][1], e))
            else:
                padded.append((s, e))

        out: list[np.ndarray] = []
        prev_end = 0
        max_len = int(self.max_speech_seconds * self.sample_rate)
        for start, end in padded:
            start = max(start, prev_end)
            if end <= start:
                continue
            # Safety net: enforce the length cap even if the VAD back end
            # ever returns a longer span.
            while end - start > max_len and max_len > 0:
                out.append(np.ascontiguousarray(pcm[start : start + max_len]))
                start += max_len
            if end > start:
                out.append(np.ascontiguousarray(pcm[start:end]))
            prev_end = end
        return out


def download_vad_model(
    on_progress: Callable[..., None] | None = None,
    on_log: Callable[[str], None] | None = None,
) -> str:
    """Download silero_vad.onnx into the models dir if missing. Returns its path."""
    on_progress = on_progress or (lambda *a, **k: None)
    on_log = on_log or (lambda _msg: None)

    dest = vad_model_path()
    if os.path.isfile(dest):
        on_log(f"[VAD] Model already present: {dest}")
        return dest

    models_root = get_models_dir()
    os.makedirs(models_root, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        prefix="silero_vad-", suffix=".onnx.tmp", dir=models_root
    )
    os.close(fd)
    try:
        on_log(f"[VAD] Downloading Silero VAD model:\n[VAD] URL: {VAD_MODEL_URL}")
        req = urllib.request.Request(VAD_MODEL_URL, headers={"User-Agent": "Vox/1.1"})
        downloaded = 0
        with urllib.request.urlopen(req) as resp:  # nosec: trusted release URL
            total = int(resp.headers.get("Content-Length", "-1"))
            on_progress(0, total, "Загрузка")
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    on_progress(downloaded, total, "Загрузка")
        os.replace(tmp_path, dest)
        on_log(f"[VAD] Installed: {dest}")
        on_progress(1, 1, "Готово")
        return dest
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)
        raise


if __name__ == "__main__":
    import wave as _wave

    _candidates = ["/tmp/opencode/silero_vad.onnx", vad_model_path()]
    _model = next((p for p in _candidates if os.path.isfile(p)), None)
    print(f"model: {_model or '(missing)'}")
    print(f"is_available(): {is_available()}")

    _sr = 16000
    # Prefer a real speech file when available (pure tones are not reliably
    # classified as speech by Silero); fall back to a synthetic signal.
    _repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _wav_candidates = [
        os.path.join(_repo_root, "sample_ru.wav"),
        os.path.join(os.getcwd(), "sample_ru.wav"),
    ]
    _pcm: np.ndarray | None = None
    _wav = next((p for p in _wav_candidates if os.path.isfile(p)), None)
    if _wav is not None:
        with _wave.open(_wav, "rb") as _w:
            assert _w.getnchannels() == 1 and _w.getsampwidth() == 2
            _sr = _w.getframerate()
            _pcm = np.frombuffer(_w.readframes(_w.getnframes()), dtype=np.int16).copy()
        print(f"test signal: {_wav} ({len(_pcm) / _sr:.1f} s int16 @ {_sr} Hz)")
    else:
        _t = np.arange(3 * _sr) / _sr
        _burst = (0.5 * np.sin(2 * np.pi * 220.0 * _t) * 32767).astype(np.int16)
        _silence = np.zeros(_sr, dtype=np.int16)
        _t2 = np.arange(3 * _sr) / _sr
        _burst2 = (0.5 * np.sin(2 * np.pi * 330.0 * _t2) * 32767).astype(np.int16)
        _pcm = np.concatenate([_burst, _silence, _burst2])
        print(f"test signal: synthetic ({len(_pcm) / _sr:.1f} s int16 @ {_sr} Hz)")

    _seg = SpeechSegmenter(model_path=_model)
    _res = _seg.split(_pcm)
    print(f"detected {len(_res)} segment(s):")
    for _i, _s in enumerate(_res):
        print(f"  [{_i}] len={len(_s)} samples ({len(_s) / _sr:.2f} s) dtype={_s.dtype}")

    print(f"empty input -> {_seg.split(np.zeros(0, dtype=np.int16))}")
    _missing = SpeechSegmenter(model_path="/nonexistent/silero_vad.onnx").split(_pcm)
    print(f"missing model -> {_missing} (len={len(_missing)})")
