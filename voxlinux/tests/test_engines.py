"""Unit tests for voxapp.engines (STT chunking + decode guards)."""
from __future__ import annotations

import gc
import importlib
import os
import tempfile
import unittest
import wave

import numpy as np

from voxapp import audio as preprocessing
from voxapp import config
from voxapp import engines
from voxapp import registry
from voxapp import vad

SAMPLE_RATE = config.SAMPLE_RATE
MODEL_ID = "gigaam-v3-e2e-rnnt-punct"


def _sine(seconds: float, sr: int = SAMPLE_RATE, freq: float = 440.0) -> np.ndarray:
    n = int(seconds * sr)
    t = np.arange(n, dtype=np.float64)
    return (np.sin(2.0 * np.pi * freq * t / sr) * 10000.0).astype(np.int16)


class EngineTranscribeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not registry.is_installed(MODEL_ID):
            raise unittest.SkipTest(f"model {MODEL_ID!r} not installed")
        cls.engine = engines.build_engine(MODEL_ID)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.engine.unload()
        except Exception:
            pass
        gc.collect()

    def _patch_decode(self):
        calls = {"n": 0}

        def fake(samples):
            calls["n"] += 1
            return f"part{calls['n']}"

        orig = self.engine._decode
        self.engine._decode = fake
        return calls, orig

    def test_short_audio_single_decode(self) -> None:
        calls, orig = self._patch_decode()
        try:
            pcm = _sine(5.0)
            result = self.engine.transcribe(pcm)
        finally:
            self.engine._decode = orig
        self.assertEqual(calls["n"], 1)
        self.assertEqual(result, "part1")

    def test_long_audio_multiple_decodes(self) -> None:
        calls, orig = self._patch_decode()
        try:
            pcm = _sine(60.0)
            samples = preprocessing.prepare(pcm, SAMPLE_RATE)
            produced = self.engine._segments(samples)
            result = self.engine.transcribe(pcm)
        finally:
            self.engine._decode = orig
        self.assertGreater(calls["n"], 1)
        self.assertEqual(calls["n"], len(produced))
        for i in range(1, calls["n"] + 1):
            self.assertIn(f"part{i}", result)

    def test_empty_audio_returns_empty(self) -> None:
        result = self.engine.transcribe(np.array([], dtype=np.int16))
        self.assertEqual(result, "")

    def test_overlong_single_chunk_raises_valueerror(self) -> None:
        orig_segments = self.engine._segments
        orig_decode = self.engine._decode
        try:
            self.engine._segments = lambda samples: [
                np.zeros(int(200 * SAMPLE_RATE), dtype=np.float32)
            ]
            self.engine._decode = lambda samples: "x"
            pcm = _sine(60.0)
            with self.assertRaises(ValueError):
                self.engine.transcribe(pcm)
        finally:
            self.engine._segments = orig_segments
            self.engine._decode = orig_decode

class VadAbsentDecodeTests(unittest.TestCase):
    def setUp(self) -> None:
        if not registry.is_installed(MODEL_ID):
            raise unittest.SkipTest(f"model {MODEL_ID!r} not installed")
        self._old_xdg = os.environ.get("XDG_DATA_HOME")
        self._orig_models = config.get_models_dir()
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["XDG_DATA_HOME"] = self._tmp.name
        importlib.reload(config)
        models_dir = config.get_models_dir()
        os.makedirs(models_dir, exist_ok=True)
        entry = registry.MODELS[MODEL_ID]
        src = os.path.join(self._orig_models, entry["extracted_dir"])
        dst = os.path.join(models_dir, entry["extracted_dir"])
        if os.path.isdir(src) and not os.path.exists(dst):
            os.symlink(src, dst)
        self.engine = engines.build_engine(MODEL_ID)
        self.assertTrue(
            not vad.is_available(),
            "VAD model must be absent in the scratch models dir",
        )

    def tearDown(self) -> None:
        try:
            self.engine.unload()
        except Exception:
            pass
        gc.collect()
        if self._old_xdg is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = self._old_xdg
        importlib.reload(config)
        self._tmp.cleanup()

    def test_220s_decodes_via_fixed_windows(self) -> None:
        calls = {"n": 0}

        def fake(samples):
            calls["n"] += 1
            return f"part{calls['n']}"

        orig = self.engine._decode
        self.engine._decode = fake
        try:
            pcm = _sine(220.0)
            samples = preprocessing.prepare(pcm, SAMPLE_RATE)
            produced = self.engine._segments(samples)
            # Fallback (fixed 30 s windows) must be used when VAD is absent.
            self.assertEqual(self.engine._segmenter_or_none(), None)
            result = self.engine.transcribe(pcm)
        finally:
            self.engine._decode = orig
        self.assertGreater(calls["n"], 1)
        self.assertEqual(calls["n"], len(produced))
        # 220 s / 30 s -> at least 7 fixed windows.
        self.assertGreaterEqual(len(produced), 7)


class RegistryInstalledTests(unittest.TestCase):
    def _run_with_scratch_models(self, populate):
        old_xdg = os.environ.get("XDG_DATA_HOME")
        tmp = tempfile.TemporaryDirectory()
        os.environ["XDG_DATA_HOME"] = tmp.name
        importlib.reload(config)
        try:
            mid = next(iter(registry.MODELS))
            base = registry.model_dir(mid)
            os.makedirs(base, exist_ok=True)
            populate(base, mid)
            return registry.is_installed(mid), mid
        finally:
            if old_xdg is None:
                os.environ.pop("XDG_DATA_HOME", None)
            else:
                os.environ["XDG_DATA_HOME"] = old_xdg
            importlib.reload(config)
            tmp.cleanup()

    def test_unknown_id_false(self) -> None:
        self.assertFalse(registry.is_installed("no-such-model-xyz"))

    def test_missing_file_false(self) -> None:
        result, _ = self._run_with_scratch_models(lambda base, mid: None)
        self.assertFalse(result)

    def test_all_files_present_true(self) -> None:
        def populate(base, mid):
            for rel in registry.MODELS[mid]["files"].values():
                path = os.path.join(base, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8"):
                    pass

        result, _ = self._run_with_scratch_models(populate)
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
