#!/usr/bin/env python3
"""Benchmark Russian ASR models (VoxLinux) on a small reference set.

Usage:
    python scripts/bench_models.py EVAL_DIR [--model ID]... [--limit N] [--out PATH]

EVAL_DIR must contain audio files (wav) and a refs.json mapping
filename -> reference transcript.

Prints a table per model: raw/normalised WER and CER, RTF, mean decode
latency. Optionally writes a markdown summary to --out.

NORMALISATION (vendor-style)
----------------------------
The vendor's published WER table (salute-developers/GigaAM/evaluation.md)
marks the end-to-end ("*-punct") models with an asterisk and states that
those numbers are computed "with post-processing applied (removing
punctuation and capitalization, replacing numerals, etc.)". The plain
models' numbers are NOT marked, i.e. they are reported on rawer text.
Therefore the two families are not directly comparable on the vendor's
single WER column.

To make them comparable we report TWO metrics:

  * raw WER/CER   - Levenshtein on whitespace-tokenised, case- and
                    punctuation-preserving strings exactly as the engine
                    and the reference emit them. No lowercasing, no
                    punctuation removal, no number conversion. This is the
                    "as-is" number.
  * normalised    - both reference and hypothesis are transformed by:
                      1. lowercasing;
                      2. replacing every punctuation character with a
                         space (i.e. stripping punctuation);
                      3. collapsing repeated whitespace;
                      4. converting spoken number-words to digits via the
                         project's own ITN (voxapp.itn.apply_itn), so
                         that "пять" and "5" compare equal ("treat
                         digits/words as equivalent");
    then Levenshtein on words (WER) / characters (CER).

Both are reported so the reader can see the effect of the vendor's
post-processing and decide which column matters for their use case.

WER/CER are micro-averaged: sum of edit distances / sum of reference
lengths over all utterances. RTF = total decode time / total audio
duration. Mean decode latency = arithmetic mean of per-utterance
transcribe() wall-clock times.

The script loads models through voxapp.engines.build_engine so that the
benchmark exercises the exact code path the app runs, including Silero VAD
chunking and audio preprocessing (DC removal, silence trim, peak norm).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from voxapp.config import SAMPLE_RATE
from voxapp.engines import build_engine
from voxapp.itn import apply_itn
from voxapp.registry import MODELS, is_installed


def read_wav_mono16k(path: str) -> np.ndarray:
    with wave.open(path, "rb") as wf:
        n_channels = wf.getnchannels()
        width = wf.getsampwidth()
        src_rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())

    if width != 2:
        raise ValueError(f"Only 16-bit PCM WAV supported, got {width * 8}-bit")
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


def levenshtein(a, b):
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1]


def wer(ref: str, hyp: str):
    r = ref.split()
    h = hyp.split()
    return levenshtein(r, h), len(r)


def cer(ref: str, hyp: str):
    r = list("".join(ref.split()))
    h = list("".join(hyp.split()))
    return levenshtein(r, h), len(r)


def normalize(text: str) -> str:
    text = text.lower()
    out = []
    for ch in text:
        if ch.isalnum() or ch.isspace():
            out.append(ch)
        else:
            out.append(" ")
    text = " ".join("".join(out).split())
    try:
        text = apply_itn(text, lang="ru")
    except Exception:
        pass
    return " ".join(text.split())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Benchmark ASR models on a reference set.")
    ap.add_argument("eval_dir", help="directory with audio + refs.json")
    ap.add_argument("--model", action="append", default=None,
                    help="model id (repeatable). Default: all installed models.")
    ap.add_argument("--limit", type=int, default=None, help="limit number of utterances")
    ap.add_argument("--out", default=None, help="write markdown summary to this path")
    args = ap.parse_args(argv)

    eval_dir = Path(args.eval_dir)
    refs_path = eval_dir / "refs.json"
    if not refs_path.is_file():
        print(f"refs.json not found in {eval_dir}", file=sys.stderr)
        return 2
    with open(refs_path, encoding="utf-8") as f:
        refs = json.load(f)

    items = sorted(refs.items())
    if args.limit is not None:
        items = items[:args.limit]

    utterances = []
    for name, ref in items:
        audio_path = eval_dir / name
        if not audio_path.is_file():
            audio_path = eval_dir / "audio" / name
        if not audio_path.is_file():
            print(f"audio file not found: {name}", file=sys.stderr)
            continue
        pcm = read_wav_mono16k(str(audio_path))
        dur = pcm.size / SAMPLE_RATE
        utterances.append((name, pcm, dur, ref))

    if not utterances:
        print("no utterances loaded", file=sys.stderr)
        return 2

    total_audio_s = sum(u[2] for u in utterances)

    models = args.model
    if not models:
        models = [mid for mid in MODELS if is_installed(mid)]
    for mid in models:
        if mid not in MODELS:
            print(f"unknown model {mid}", file=sys.stderr)
            return 2

    results = []
    for mid in models:
        print(f"\n=== {mid} ===", flush=True)
        engine = build_engine(mid)
        raw_wer_err = raw_wer_ref = 0
        norm_wer_err = norm_wer_ref = 0
        raw_cer_err = raw_cer_ref = 0
        norm_cer_err = norm_cer_ref = 0
        latencies = []
        total_decode_s = 0.0
        for name, pcm, dur, ref in utterances:
            t0 = time.perf_counter()
            hyp = engine.transcribe(pcm)
            dt = time.perf_counter() - t0
            latencies.append(dt)
            total_decode_s += dt

            e, n = wer(ref, hyp)
            raw_wer_err += e; raw_wer_ref += n
            e, n = cer(ref, hyp)
            raw_cer_err += e; raw_cer_ref += n

            ref_n = normalize(ref)
            hyp_n = normalize(hyp)
            e, n = wer(ref_n, hyp_n)
            norm_wer_err += e; norm_wer_ref += n
            e, n = cer(ref_n, hyp_n)
            norm_cer_err += e; norm_cer_ref += n

        engine.unload()

        rtf = total_decode_s / total_audio_s if total_audio_s > 0 else 0.0
        mean_lat = sum(latencies) / len(latencies) if latencies else 0.0
        res = {
            "model": mid,
            "raw_wer": 100.0 * raw_wer_err / raw_wer_ref if raw_wer_ref else 0.0,
            "norm_wer": 100.0 * norm_wer_err / norm_wer_ref if norm_wer_ref else 0.0,
            "raw_cer": 100.0 * raw_cer_err / raw_cer_ref if raw_cer_ref else 0.0,
            "norm_cer": 100.0 * norm_cer_err / norm_cer_ref if norm_cer_ref else 0.0,
            "rtf": rtf,
            "mean_latency": mean_lat,
            "n": len(utterances),
            "audio_s": total_audio_s,
            "decode_s": total_decode_s,
        }
        results.append(res)
        print(f"raw WER {res['raw_wer']:.2f}% | norm WER {res['norm_wer']:.2f}% | "
              f"raw CER {res['raw_cer']:.2f}% | norm CER {res['norm_cer']:.2f}% | "
              f"RTF {res['rtf']:.3f} | mean lat {res['mean_latency']:.3f}s")

    print()
    header = f"{'model':32s} {'rawWER%':>8s} {'normWER%':>9s} {'rawCER%':>8s} {'normCER%':>9s} {'RTF':>6s} {'meanLat(s)':>10s}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(f"{r['model']:32s} {r['raw_wer']:8.2f} {r['norm_wer']:9.2f} "
              f"{r['raw_cer']:8.2f} {r['norm_cer']:9.2f} {r['rtf']:6.3f} "
              f"{r['mean_latency']:10.3f}")

    if args.out:
        lines = []
        lines.append("# VoxLinux ASR benchmark results")
        lines.append("")
        lines.append(f"- Eval dir: `{eval_dir}`")
        lines.append(f"- Utterances: {len(utterances)}")
        lines.append(f"- Total audio: {total_audio_s:.2f} s ({total_audio_s/60:.2f} min)")
        lines.append(f"- Models: {', '.join(models)}")
        lines.append("")
        lines.append("## Measured table")
        lines.append("")
        lines.append("| model | raw WER % | norm WER % | raw CER % | norm CER % | RTF | mean decode latency (s) |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for r in results:
            lines.append(f"| {r['model']} | {r['raw_wer']:.2f} | {r['norm_wer']:.2f} | "
                         f"{r['raw_cer']:.2f} | {r['norm_cer']:.2f} | {r['rtf']:.3f} | "
                         f"{r['mean_latency']:.3f} |")
        lines.append("")
        lines.append("## Normalisation rule")
        lines.append("")
        lines.append("Raw = Levenshtein on whitespace-tokenised strings as emitted "
                     "(case- and punctuation-preserving).")
        lines.append("Normalised = lowercase -> punctuation to spaces -> collapse "
                     "whitespace -> ITN number-words to digits -> Levenshtein.")
        lines.append("")
        lines.append("WER/CER are micro-averaged (sum edits / sum reference length). "
                     "RTF = total decode time / total audio duration.")
        lines.append("")
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"\nWrote {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
