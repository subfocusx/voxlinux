"""
Speech recognition engines.

One backend: sherpa-onnx, running the bundled NeMo models (GigaAM v3,
Russian). Two model families are supported:

  * neMo CTC          — one ONNX file + tokens, greedy decode;
  * NeMo transducer   — encoder + decoder + joiner + tokens, greedy decode.

The engine takes int16 PCM mono at SAMPLE_RATE Hz and returns text.

Long dictations are split into speech segments before decoding: the GigaAM v3
encoder holds 5000 positional embeddings (25 encoder frames per second), so a
single decode is limited to 200 s — 199 s still works, 201 s crashes ONNX
Runtime with "Attempting to broadcast an axis by a dimension other than 1.
5000 by 5500". Splitting also keeps latency and accuracy sane on long holds.
"""

from __future__ import annotations

import gc
import os
from abc import ABC, abstractmethod

import numpy as np

from voxapp import audio as preprocessing
from voxapp.config import SAMPLE_RATE
from voxapp.registry import MODELS, model_dir


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

MAX_DECODE_SECONDS = 195.0
"""Hard ceiling for a single decode (the model itself fails at 200 s)."""

CHUNK_THRESHOLD_SECONDS = 30.0
"""Above this length the audio is cut into speech segments before decoding."""

FALLBACK_CHUNK_SECONDS = 30.0
"""Segment length used when the Silero VAD model is not installed."""

FEATURE_DIM = 64
"""Mel bins of the GigaAM frontend.

sherpa-onnx overrides this to 64 for every model carrying the "is_giga_am"
metadata (see csrc/offline-recognizer-ctc-impl.h), so the value here is only
documentation — but keeping it truthful avoids the 80-vs-64 trap that the
official docs still print.
"""


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class Engine(ABC):
    """Stateful recognizer wrapping one loaded model."""

    name: str = "base"

    @abstractmethod
    def transcribe(self, pcm_int16: np.ndarray) -> str:
        """Take 1-D int16 PCM @ SAMPLE_RATE Hz and return recognised text."""

    def unload(self) -> None:
        """Release resources. Default: no-op (GC handles it)."""



# ---------------------------------------------------------------------------
# sherpa-onnx
# ---------------------------------------------------------------------------


class SherpaEngine(Engine):
    name = "sherpa-onnx"

    def __init__(self, model_id: str):
        import sherpa_onnx

        info = MODELS[model_id]
        subtype = info["engine_subtype"]
        base = model_dir(model_id)
        # Build a `files` dict with paths inside the model directory.
        files = {key: os.path.join(base, rel) for key, rel in info["files"].items()}

        self.model_id = model_id
        self.subtype = subtype
        self._segmenter = None

        print(f"[INIT] Loading sherpa-onnx model ({subtype}): {model_id}")

        cpu_threads = max(1, (os.cpu_count() or 4) // 2)

        if subtype == "nemo-transducer":
            self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=files["encoder"],
                decoder=files["decoder"],
                joiner=files["joiner"],
                tokens=files["tokens"],
                num_threads=cpu_threads,
                sample_rate=SAMPLE_RATE,
                feature_dim=FEATURE_DIM,
                decoding_method="greedy_search",
                # Mandatory for NeMo RNN-T: the default ("transducer") picks
                # the Zipformer implementation, and auto-detection only runs
                # when model_type is empty.
                model_type="nemo_transducer",
                provider="cpu",
            )
        elif subtype == "nemo-ctc":
            self._recognizer = sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
                model=files["model"],
                tokens=files["tokens"],
                num_threads=cpu_threads,
                sample_rate=SAMPLE_RATE,
                feature_dim=FEATURE_DIM,
                decoding_method="greedy_search",
                provider="cpu",
            )
        else:
            raise ValueError(f"Unsupported sherpa-onnx subtype: {subtype}")

        print(f"[INIT] sherpa-onnx model loaded ({subtype})")

    # -- segmentation ----------------------------------------------------
    def _segmenter_or_none(self):
        """Silero VAD segmenter, or None when the VAD model is missing."""
        if self._segmenter is not None:
            return self._segmenter
        try:
            from voxapp import vad
        except ImportError:
            return None
        if not vad.is_available():
            return None
        try:
            self._segmenter = vad.SpeechSegmenter(
                sample_rate=SAMPLE_RATE, max_speech_seconds=20.0
            )
        except Exception as exc:  # a broken VAD must not break dictation
            print(f"[INIT] Silero VAD unavailable ({exc}); using fixed chunks")
            self._segmenter = None
        return self._segmenter

    def _segments(self, samples: np.ndarray) -> list[np.ndarray]:
        """Cut float32 audio into chunks that are safe to decode separately."""
        segmenter = self._segmenter_or_none()
        if segmenter is not None:
            # The segmenter works on int16; our audio is already float32.
            pcm16 = (samples * 32768.0).clip(-32768, 32767).astype(np.int16)
            try:
                chunks = segmenter.split(pcm16)
            except Exception as exc:
                print(f"[STT] VAD split failed ({exc}); using fixed chunks")
                chunks = []
            if chunks:
                return [c.astype(np.float32) / 32768.0 for c in chunks]

        # Fallback: fixed-size windows. Boundaries may cut a word, but the
        # alternative (one huge decode) crashes the model past 200 s.
        step = int(FALLBACK_CHUNK_SECONDS * SAMPLE_RATE)
        return [samples[i : i + step] for i in range(0, len(samples), step)]

    # -- decoding --------------------------------------------------------
    def _decode(self, samples: np.ndarray) -> str:
        stream = self._recognizer.create_stream()
        stream.accept_waveform(SAMPLE_RATE, samples)
        self._recognizer.decode_stream(stream)
        return (stream.result.text or "").strip()

    def transcribe(self, pcm_int16: np.ndarray, trim: bool = True,
                   normalize: bool = True) -> str:
        samples = preprocessing.prepare(pcm_int16, SAMPLE_RATE, trim=trim,
                                        normalize=normalize)
        if samples.size == 0:
            return ""

        duration = samples.size / SAMPLE_RATE

        if duration <= CHUNK_THRESHOLD_SECONDS:
            return self._decode(samples)

        # Longer than one chunk: split into speech segments and decode them
        # one by one. This is what keeps a long dictation inside the model's
        # ~200 s limit (a single decode of 201 s crashes ONNX Runtime).
        chunks = self._segments(samples)
        if not chunks:
            if duration > MAX_DECODE_SECONDS:
                raise ValueError(
                    f"audio is {duration:.1f}s, the limit is {MAX_DECODE_SECONDS:.0f}s; "
                    "reduce the recording length"
                )
            return self._decode(samples)

        for chunk in chunks:
            chunk_seconds = chunk.size / SAMPLE_RATE
            if chunk_seconds > MAX_DECODE_SECONDS:
                raise ValueError(
                    f"segment is {chunk_seconds:.1f}s, the limit is "
                    f"{MAX_DECODE_SECONDS:.0f}s"
                )

        parts = [t for t in (self._decode(c) for c in chunks) if t]
        return " ".join(parts)

    def unload(self) -> None:
        self._recognizer = None
        self._segmenter = None
        gc.collect()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_engine(model_id: str) -> Engine:
    """Construct the right Engine instance for the given catalog entry."""
    if model_id not in MODELS:
        raise KeyError(f"Unknown model id: {model_id}")
    info = MODELS[model_id]
    eng_type = info["engine"]
    if eng_type == "sherpa-onnx":
        return SherpaEngine(model_id)
    raise ValueError(f"Unknown engine type: {eng_type}")
