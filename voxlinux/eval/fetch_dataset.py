#!/usr/bin/env python3
"""Reproduce the VoxLinux ASR evaluation dataset.

Downloads the source parquet(s) listed in eval/data/manifest.json from
Hugging Face (bond005/sberdevices_golos_10h_crowd), extracts exactly the
rows recorded there, writes them as 16 kHz mono int16 WAV into
eval/data/audio/, and verifies each file against the PCM SHA-256 in the
manifest.

Usage:
    python eval/fetch_dataset.py                 # fetch + verify
    python eval/fetch_dataset.py --check         # verify local files only
    python eval/fetch_dataset.py --cache-dir DIR # override cache location
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import urllib.request
import wave
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
MANIFEST_PATH = DATA_DIR / "manifest.json"
AUDIO_DIR = DATA_DIR / "audio"
DEFAULT_CACHE_DIR = Path("/tmp/opencode/eval-cache")


def _load_manifest(manifest_path: Path) -> dict:
    if not manifest_path.is_file():
        print(f"manifest not found: {manifest_path}", file=sys.stderr)
        sys.exit(2)
    with open(manifest_path, encoding="utf-8") as f:
        return json.load(f)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_wav_pcm(path: Path):
    with wave.open(str(path), "rb") as wf:
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        sr = wf.getframerate()
        n = wf.getnframes()
        frames = wf.readframes(n)
    return ch, sw, sr, n, frames


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    try:
        with urllib.request.urlopen(url) as resp, open(tmp, "wb") as f:
            shutil.copyfileobj(resp, f)
        os.replace(tmp, dest)
    except Exception as e:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise RuntimeError(f"failed to download {url}: {e}") from e


def _extract_pcm_from_parquet_row(parquet_path: Path, row_index: int):
    try:
        import pyarrow.parquet as pq
    except ImportError as e:
        raise RuntimeError(
            "pyarrow is required to read parquet; run with the project venv "
            "(./.venv/bin/python) or install pyarrow in a scratch venv"
        ) from e
    table = pq.read_table(str(parquet_path))
    audio_col = table.column("audio")
    if row_index < 0 or row_index >= table.num_rows:
        raise RuntimeError(
            f"row_index {row_index} out of range (0..{table.num_rows - 1}) "
            f"in {parquet_path}"
        )
    row = audio_col[row_index].as_py()
    wav_bytes = row.get("bytes")
    if not wav_bytes:
        raise RuntimeError(f"no audio bytes at row {row_index} in {parquet_path}")
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        sr = wf.getframerate()
        n = wf.getnframes()
        frames = wf.readframes(n)
    return ch, sw, sr, n, frames, wav_bytes


def cmd_check(manifest: dict, audio_dir: Path) -> int:
    entries = manifest["files"]
    ok = True
    n_ok = 0
    for entry in entries:
        path = audio_dir / entry["filename"]
        if not path.is_file():
            print(f"MISSING  {path}", file=sys.stderr)
            ok = False
            continue
        try:
            ch, sw, sr, n, frames = _read_wav_pcm(path)
        except Exception as e:
            print(f"UNREADABLE {path}: {e}", file=sys.stderr)
            ok = False
            continue
        h = _sha256_bytes(frames)
        problems = []
        if ch != entry["channels"]:
            problems.append(f"channels {ch} != {entry['channels']}")
        if sw != entry["sample_width"]:
            problems.append(f"sample_width {sw} != {entry['sample_width']}")
        if sr != entry["sample_rate"]:
            problems.append(f"sample_rate {sr} != {entry['sample_rate']}")
        if n != entry["num_samples"]:
            problems.append(f"num_samples {n} != {entry['num_samples']}")
        if h != entry["pcm_sha256"]:
            problems.append(f"pcm_sha256 {h} != {entry['pcm_sha256']}")
        if problems:
            print(f"MISMATCH {entry['filename']}: " + "; ".join(problems), file=sys.stderr)
            ok = False
        else:
            n_ok += 1
            print(f"OK       {entry['filename']}")
    print(f"checked {len(entries)} files: {n_ok} ok, {len(entries) - n_ok} bad")
    return 0 if ok else 1


def cmd_fetch(manifest: dict, cache_dir: Path, audio_dir: Path) -> int:
    dataset = manifest["dataset"]
    base = manifest.get("hf_resolve_base") or (
        "https://huggingface.co/datasets/" + dataset + "/resolve/main/"
    )
    if not base.endswith("/"):
        base = base + "/"

    audio_dir.mkdir(parents=True, exist_ok=True)

    source_files = manifest.get("source_files") or sorted(
        {e["source_file"] for e in manifest["files"]}
    )

    parquet_paths = {}
    for sf in source_files:
        url = base + sf
        dest = cache_dir / sf
        if dest.is_file() and dest.stat().st_size > 0:
            print(f"cached   {sf}")
        else:
            print(f"download {sf}")
            try:
                _download(url, dest)
            except Exception as e:
                print(str(e), file=sys.stderr)
                return 1
        parquet_paths[sf] = dest

    n_ok = 0
    for entry in manifest["files"]:
        sf = entry["source_file"]
        pq_path = parquet_paths[sf]
        try:
            ch, sw, sr, n, frames, wav_bytes = _extract_pcm_from_parquet_row(pq_path, entry["row_index"])
        except Exception as e:
            print(f"EXTRACT FAIL {entry['filename']}: {e}", file=sys.stderr)
            return 1

        problems = []
        if ch != entry["channels"]:
            problems.append(f"channels {ch} != {entry['channels']}")
        if sw != entry["sample_width"]:
            problems.append(f"sample_width {sw} != {entry['sample_width']}")
        if sr != entry["sample_rate"]:
            problems.append(f"sample_rate {sr} != {entry['sample_rate']}")
        if n != entry["num_samples"]:
            problems.append(f"num_samples {n} != {entry['num_samples']}")
        h = _sha256_bytes(frames)
        if h != entry["pcm_sha256"]:
            problems.append(f"pcm_sha256 {h} != {entry['pcm_sha256']}")
        if problems:
            print(f"VERIFY FAIL {entry['filename']}: " + "; ".join(problems), file=sys.stderr)
            return 1

        out_path = audio_dir / entry["filename"]
        try:
            with open(out_path, "wb") as f:
                f.write(wav_bytes)
        except Exception as e:
            print(f"WRITE FAIL {out_path}: {e}", file=sys.stderr)
            return 1

        try:
            vch, vsw, vsr, vn, vframes = _read_wav_pcm(out_path)
        except Exception as e:
            print(f"READBACK FAIL {out_path}: {e}", file=sys.stderr)
            return 1
        vh = _sha256_bytes(vframes)
        rproblems = []
        if vch != entry["channels"] or vsw != entry["sample_width"] or vsr != entry["sample_rate"] or vn != entry["num_samples"] or vh != entry["pcm_sha256"]:
            rproblems.append("written file does not match manifest")
        if rproblems:
            print(f"POST-VERIFY FAIL {entry['filename']}: " + "; ".join(rproblems), file=sys.stderr)
            return 1
        n_ok += 1
        print(f"WROTE    {entry['filename']}  (row {entry['row_index']})")

    print(f"fetched {n_ok}/{len(manifest['files'])} files into {audio_dir}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Fetch/verify the VoxLinux ASR eval dataset.")
    ap.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR),
                    help="cache directory for downloaded parquet (default: /tmp/opencode/eval-cache)")
    ap.add_argument("--audio-dir", default=None,
                    help="output audio directory (default: eval/data/audio)")
    ap.add_argument("--manifest", default=None, help="path to manifest.json")
    ap.add_argument("--check", action="store_true",
                    help="verify existing local files only, no download")
    args = ap.parse_args(argv)

    manifest_path = Path(args.manifest) if args.manifest else MANIFEST_PATH
    manifest = _load_manifest(manifest_path)
    audio_dir = Path(args.audio_dir) if args.audio_dir else AUDIO_DIR
    cache_dir = Path(args.cache_dir)

    if args.check:
        return cmd_check(manifest, audio_dir)
    return cmd_fetch(manifest, cache_dir, audio_dir)


if __name__ == "__main__":
    sys.exit(main())
