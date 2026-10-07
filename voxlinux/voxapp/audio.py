"""Audio pre-processing before STT.

CTC models (GigaAM v3) are sensitive to what surrounds the speech:
leading/trailing silence smears the alignment, DC offset shifts every
logit, and a quiet mic produces flat posteriors. All steps are plain
numpy, no extra dependencies.

Pipeline (`prepare`): DC-remove → energy trim → peak normalize.
"""

from __future__ import annotations

import numpy as np

SILENCE_DB = -40.0
"""Frames quieter than this (vs peak) count as silence."""

FRAME_MS = 20.0
"""Energy analysis frame length."""

PAD_MS = 180.0
"""Speech padding kept on each side after trimming."""

TARGET_PEAK = 0.9
"""Normalize so the peak hits this (float32, [-1, 1] scale)."""


def remove_dc(pcm: np.ndarray) -> np.ndarray:
    """Subtract the mean (DC offset) in float32."""
    x = pcm.astype(np.float32)
    return x - x.mean()


def trim_silence(
    x: np.ndarray,
    sample_rate: int,
    silence_db: float = SILENCE_DB,
    pad_ms: float = PAD_MS,
) -> np.ndarray:
    """Cut leading/trailing silence, keeping `pad_ms` of context each side."""
    if x.size == 0:
        return x
    frame = max(1, int(sample_rate * FRAME_MS / 1000.0))
    pad_frames = int(pad_ms / FRAME_MS)
    peak = float(np.max(np.abs(x)))
    if peak <= 0:
        return x
    thresh = peak * 10.0 ** (silence_db / 20.0)
    n = (x.size + frame - 1) // frame
    energy = np.array(
        [np.max(np.abs(x[i * frame:(i + 1) * frame])) for i in range(n)]
    )
    voiced = np.nonzero(energy >= thresh)[0]
    if voiced.size == 0:
        return x
    start = max(0, int(voiced[0]) - pad_frames) * frame
    end = min(x.size, (int(voiced[-1]) + 1 + pad_frames) * frame)
    return x[start:end] if end > start else x


def normalize_peak(x: np.ndarray, target: float = TARGET_PEAK) -> np.ndarray:
    """Scale to `target` peak with clipping guard."""
    peak = float(np.max(np.abs(x)))
    if peak <= 0:
        return x
    return np.clip(x * (target / peak), -1.0, 1.0)


def prepare(
    pcm_int16: np.ndarray,
    sample_rate: int,
    trim: bool = True,
    normalize: bool = True,
) -> np.ndarray:
    """Full chain: int16 in → clean float32 in [-1, 1] out."""
    x = remove_dc(pcm_int16) / 32768.0
    if trim:
        x = trim_silence(x, sample_rate)
    if normalize:
        x = normalize_peak(x)
    return x.astype(np.float32)
