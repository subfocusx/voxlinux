"""
Speech recognition engines.

One backend: sherpa-onnx, running the bundled NeMo transducer model
(GigaAM v3, Russian).

The engine takes int16 PCM mono at SAMPLE_RATE Hz and returns text.
"""

from __future__ import annotations

import gc
import os
from abc import ABC, abstractmethod

import numpy as np

from voxapp.config import SAMPLE_RATE
from voxapp.registry import MODELS, model_dir


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
                feature_dim=80,
                model_type="nemo_transducer",
                provider="cpu",
            )
        elif subtype == "nemo-ctc":
            self._recognizer = sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
                model=files["model"],
                tokens=files["tokens"],
                num_threads=cpu_threads,
                sample_rate=SAMPLE_RATE,
                feature_dim=80,
                decoding_method="greedy_search",
                provider="cpu",
            )
        else:
            raise ValueError(f"Unsupported sherpa-onnx subtype: {subtype}")

        print(f"[INIT] sherpa-onnx model loaded ({subtype})")

    def transcribe(self, pcm_int16: np.ndarray) -> str:
        # sherpa-onnx expects float32 normalised to [-1, 1]
        samples = pcm_int16.astype(np.float32) / 32768.0
        stream = self._recognizer.create_stream()
        stream.accept_waveform(SAMPLE_RATE, samples)
        self._recognizer.decode_stream(stream)
        return (stream.result.text or "").strip()

    def unload(self) -> None:
        self._recognizer = None
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
