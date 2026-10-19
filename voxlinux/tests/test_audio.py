"""Unit tests for voxapp.audio pre-processing helpers."""
from __future__ import annotations

import unittest

import numpy as np

from voxapp import audio


def _sine(n: int, freq: float = 440.0, sr: int = 16000) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / sr
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


class RemoveDcTest(unittest.TestCase):
    def test_mean_is_zero_afterwards(self) -> None:
        x = _sine(16000) + 0.3
        out = audio.remove_dc(x)
        self.assertAlmostEqual(float(out.mean()), 0.0, places=5)

    def test_returns_float32(self) -> None:
        x = (np.arange(100, dtype=np.int16) * 10).astype(np.int16)
        out = audio.remove_dc(x)
        self.assertEqual(out.dtype, np.float32)


class TrimSilenceTest(unittest.TestCase):
    def test_keeps_speech_drops_edges(self) -> None:
        sr = 16000
        silence = np.zeros(sr, dtype=np.float32)  # 1 s of silence each side
        speech = _sine(sr)
        x = np.concatenate([silence, speech, silence])
        out = audio.trim_silence(x, sr)
        self.assertLess(len(out), len(x))
        # Speech itself must survive: peak of trimmed output stays high.
        self.assertGreater(float(np.max(np.abs(out))), 0.4)

    def test_empty_array_is_safe(self) -> None:
        x = np.array([], dtype=np.float32)
        out = audio.trim_silence(x, 16000)
        self.assertEqual(out.size, 0)

    def test_all_silent_returns_input(self) -> None:
        x = np.zeros(8000, dtype=np.float32)
        out = audio.trim_silence(x, 16000)
        self.assertIs(out, x)

    def test_all_zero_int_returns_input(self) -> None:
        x = np.zeros(8000, dtype=np.int16)
        out = audio.trim_silence(x, 16000)
        self.assertIs(out, x)

    def test_pure_speech_kept_whole(self) -> None:
        x = _sine(16000)
        out = audio.trim_silence(x, 16000)
        self.assertEqual(len(out), len(x))


class NormalizePeakTest(unittest.TestCase):
    def test_peak_hits_target(self) -> None:
        x = np.array([0.1, -0.2, 0.05], dtype=np.float32)
        out = audio.normalize_peak(x, target=0.9)
        self.assertAlmostEqual(float(np.max(np.abs(out))), 0.9, places=5)

    def test_clipping_guard(self) -> None:
        x = np.array([10.0, -3.0, 0.5], dtype=np.float32)
        out = audio.normalize_peak(x)
        self.assertLessEqual(float(np.max(np.abs(out))), 1.0)

    def test_silent_input_returned_unchanged(self) -> None:
        x = np.zeros(100, dtype=np.float32)
        out = audio.normalize_peak(x)
        self.assertIs(out, x)


class PrepareTest(unittest.TestCase):
    def test_composition_int16_to_float32(self) -> None:
        sr = 16000
        silence = np.zeros(sr // 2, dtype=np.float32)
        speech = _sine(sr)
        mixed = np.concatenate([silence, speech, silence])
        pcm = (mixed * 32767).astype(np.int16)
        out = audio.prepare(pcm, sr)
        self.assertEqual(out.dtype, np.float32)
        self.assertLess(len(out), len(pcm))
        self.assertAlmostEqual(float(np.max(np.abs(out))), audio.TARGET_PEAK, places=4)
        self.assertLessEqual(float(np.max(np.abs(out))), 1.0)
        self.assertAlmostEqual(float(out.mean()), 0.0, places=2)

    def test_trim_and_normalize_can_be_disabled(self) -> None:
        pcm = (np.ones(16000, dtype=np.float32) * 0.1 * 32767).astype(np.int16)
        out = audio.prepare(pcm, 16000, trim=False, normalize=False)
        self.assertEqual(len(out), len(pcm))
        self.assertAlmostEqual(float(out.mean()), 0.0, places=4)


if __name__ == "__main__":
    unittest.main()
