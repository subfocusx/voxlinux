#!/usr/bin/env python3
"""
Transcribe a Russian WAV file through the full VoxLinux pipeline.

Usage:
    python scripts/test_transcribe.py sample_ru.wav

Reads a WAV file (any sample rate / channel count — it is resampled to
16 kHz mono on the fly), runs it through the sherpa-onnx GigaAM v3 engine
and then through the post-processing pipeline (terms → fillers → ITN →
sentence spacing → punctuation → capitalization).

Prints the raw STT output, the processed text, per-step intermediate output
and the measured transcription time.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from voxapp.config import SAMPLE_RATE  # noqa: E402
from voxapp.engines import build_engine  # noqa: E402
from voxapp.post_processor import PostProcessor  # noqa: E402
from voxapp.registry import MODELS, DEFAULT_MODEL_ID  # noqa: E402


def read_wav_mono16k(path: str) -> np.ndarray:
    """Load a WAV file as 1-D int16 PCM at SAMPLE_RATE Hz (linear resample)."""
    with wave.open(path, "rb") as wf:
        n_channels = wf.getnchannels()
        width = wf.getsampwidth()
        src_rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())

    if width != 2:
        raise ValueError(f"Only 16-bit PCM WAV is supported, got {width * 8}-bit")
    if n_channels > 1:
        data = np.frombuffer(frames, dtype="<i2")
        usable = (data.size // n_channels) * n_channels
        samples = data[:usable].reshape(-1, n_channels).mean(axis=1).astype(np.int16)
    else:
        samples = np.frombuffer(frames, dtype="<i2")

    if src_rate != SAMPLE_RATE:
        duration = samples.size / src_rate
        target_len = int(round(duration * SAMPLE_RATE))
        x_old = np.arange(samples.size, dtype=np.float64)
        x_new = np.linspace(0.0, samples.size - 1, target_len, dtype=np.float64)
        samples = np.interp(x_new, x_old, samples.astype(np.float64)).astype(np.int16)

    return np.ascontiguousarray(samples)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Transcribe a Russian WAV file.")
    ap.add_argument("wav", help="path to a WAV file (16 kHz mono preferred)")
    ap.add_argument(
        "--model", default=DEFAULT_MODEL_ID, help=f"model id (default: {DEFAULT_MODEL_ID})"
    )
    ap.add_argument(
        "--steps", action="store_true", help="print every post-processing step's output"
    )
    args = ap.parse_args(argv)

    pcm = read_wav_mono16k(args.wav)
    duration = pcm.size / SAMPLE_RATE
    print(f"[INPUT] {args.wav}: {duration:.2f}s @ {SAMPLE_RATE} Hz mono")

    t0 = time.perf_counter()
    engine = build_engine(args.model)
    load_s = time.perf_counter() - t0

    t1 = time.perf_counter()
    raw = engine.transcribe(pcm)
    infer_s = time.perf_counter() - t1

    info = MODELS[args.model]
    pp = PostProcessor(
        lang=info.get("language", "ru"),
        enable_terms=info.get("needs_term_replace", True),
        enable_fillers=True,
        enable_itn=True,
        enable_sentence_spacing=True,
        enable_punctuation=info.get("needs_punctuation", True),
        enable_capitalization=False,
        enable_spacing=False,
        always_leading_space=False,
    )
    result = pp.process(raw)

    print()
    print(f"[RAW]       {raw}")
    print(f"[TEXT]      {result.processed.strip()}")
    if args.steps:
        for name, value in result.steps.items():
            print(f"  - {name:<18} {value}")

    rtf = infer_s / duration if duration > 0 else 0.0
    print()
    print(f"[TIMING] model load: {load_s:.2f}s")
    print(f"[TIMING] transcribe: {infer_s:.3f}s for {duration:.2f}s audio (RTF {rtf:.3f})")

    if not result.processed.strip():
        print("[ERROR] Empty recognition result.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())