"""Unit tests for voxapp.vad speech segmentation."""
from __future__ import annotations

import os
import unittest
import wave

import numpy as np

from voxapp import vad


def _find_model() -> str | None:
    for p in ("/tmp/opencode/silero_vad.onnx", vad.vad_model_path()):
        if os.path.isfile(p):
            return p
    return None


def _find_sample() -> str | None:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(here, "sample_ru.wav"),
        "/mnt/data-archive/Code/Python/vox_am/voxlinux/sample_ru.wav",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def _load_wav(path):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        pcm = np.frombuffer(w.readframes(n), dtype=np.int16).copy()
    return pcm, sr


def _speech_duration_seconds(pcm, sr, model_path):
    try:
        import sherpa_onnx
    except ImportError:
        return None
    config = sherpa_onnx.VadModelConfig()
    config.sample_rate = sr
    config.num_threads = 1
    config.silero_vad.model = model_path
    config.silero_vad.threshold = 0.5
    config.silero_vad.min_silence_duration = 0.25
    config.silero_vad.min_speech_duration = 0.25
    config.silero_vad.max_speech_duration = 20.0
    v = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30.0)
    ws = int(config.silero_vad.window_size)
    samples = (pcm.astype(np.float32) / 32768.0).tolist()
    spans = []

    def drain():
        while not v.empty():
            seg = v.front
            st = int(seg.start)
            ln = len(seg.samples)
            v.pop()
            if ln > 0:
                spans.append((st, st + ln))

    pos = 0
    total = len(samples)
    while pos + ws <= total:
        v.accept_waveform(samples[pos:pos + ws])
        pos += ws
        drain()
    if pos < total:
        v.accept_waveform(samples[pos:])
        drain()
    v.flush()
    drain()
    return sum(e - s for s, e in spans) / sr


class SpansToSegmentsTest(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual(vad._spans_to_segments([], 100, 2, 10), [])
        self.assertEqual(vad._spans_to_segments(None, 100, 2, 10), [])

    def test_all_silence_no_spans(self):
        self.assertEqual(vad._spans_to_segments([], 100, 0, 10), [])

    def test_single_span(self):
        self.assertEqual(vad._spans_to_segments([(10, 20)], 100, 0, 100), [(10, 20)])

    def test_padding_clamped_at_edges(self):
        res = vad._spans_to_segments([(0, 5), (95, 100)], 100, 4, 100)
        self.assertEqual(res[0], (0, 9))
        self.assertEqual(res[1], (91, 100))

    def test_two_spans_far_apart_stay_separate(self):
        res = vad._spans_to_segments([(10, 20), (60, 70)], 100, 3, 100)
        self.assertEqual(len(res), 2)

    def test_two_spans_close_trimmed(self):
        res = vad._spans_to_segments([(10, 20), (22, 30)], 100, 3, 100)
        self.assertEqual(res, [(7, 23), (23, 33)])
        covered = set()
        for s, e in res:
            covered.update(range(s, e))
        for s, e in [(10, 20), (22, 30)]:
            for i in range(s, e):
                self.assertIn(i, covered)
        self.assertLessEqual(res[0][1], res[1][0])

    def test_long_span_split_no_drop(self):
        res = vad._spans_to_segments([(5, 25)], 100, 0, 6)
        self.assertEqual(res, [(5, 11), (11, 17), (17, 23), (23, 25)])
        self.assertEqual(sum(e - s for s, e in res), 25 - 5)

    def test_span_end_exceeds_buffer_clipped(self):
        res = vad._spans_to_segments([(90, 200)], 100, 2, 100)
        self.assertEqual(res, [(88, 100)])

    def test_zero_edges_do_not_raise(self):
        self.assertEqual(
            vad._spans_to_segments([(1, 5), (6, 9)], 10, 0, 0), [(1, 5), (6, 9)]
        )
        self.assertEqual(vad._spans_to_segments([(0, 5)], 0, 0, 0), [])

    def test_start_clamped_before_padding(self):
        res = vad._spans_to_segments([(-5, 5)], 100, 3, 100)
        self.assertEqual(res[0][0], 0)
        self.assertEqual(res[0][1], 8)

    def test_touching_padded_ranges_no_duplicate(self):
        # padded ranges exactly touch -> no overlap, distinct segments
        res = vad._spans_to_segments([(0, 4), (10, 14)], 100, 3, 100)
        # first padded (0,7), second padded (7,17) -> trim second start to 7
        self.assertEqual(res[0][1], 7)
        self.assertLessEqual(res[0][1], res[1][0])


class SpeechSegmenterBasicTest(unittest.TestCase):
    def test_missing_model_returns_empty(self):
        seg = vad.SpeechSegmenter(model_path="/nonexistent/silero_vad.onnx")
        pcm = np.zeros(1000, dtype=np.int16)
        self.assertEqual(seg.split(pcm), [])

    def test_empty_input_returns_empty(self):
        seg = vad.SpeechSegmenter(model_path="/nonexistent/silero_vad.onnx")
        self.assertEqual(seg.split(None), [])
        self.assertEqual(seg.split(np.zeros(0, dtype=np.int16)), [])

    def test_class_static_method_matches_module(self):
        spans = [(10, 20), (22, 30)]
        a = vad._spans_to_segments(spans, 100, 3, 100)
        b = vad.SpeechSegmenter._spans_to_segments(spans, 100, 3, 100)
        self.assertEqual(a, b)


@unittest.skipUnless(_find_model() is not None and _find_sample() is not None,
                     "VAD model or sample_ru.wav missing")
class VadIntegrationTest(unittest.TestCase):
    def test_sample_ru(self):
        model = _find_model()
        sample = _find_sample()
        pcm, sr = _load_wav(sample)
        seg = vad.SpeechSegmenter(model_path=model, sample_rate=sr)
        chunks = seg.split(pcm)
        self.assertGreater(len(chunks), 0)
        total = sum(len(c) for c in chunks) / sr
        speech = _speech_duration_seconds(pcm, sr, model)
        self.assertIsNotNone(speech)
        self.assertLessEqual(abs(total - speech) / speech, 0.10)
        # first segment starts at the buffer start (word onset preserved)
        self.assertTrue(np.array_equal(chunks[0], pcm[:len(chunks[0])]))

    def test_looped_220s(self):
        model = _find_model()
        sample = _find_sample()
        pcm, sr = _load_wav(sample)
        # build ~220s loop
        repeats = int(220.0 * sr / len(pcm)) + 1
        big = np.tile(pcm, repeats)[: int(220.0 * sr)].astype(np.int16)
        seg = vad.SpeechSegmenter(model_path=model, sample_rate=sr)
        chunks = seg.split(big)
        self.assertGreater(len(chunks), 0)
        total = sum(len(c) for c in chunks) / sr
        speech = _speech_duration_seconds(big, sr, model)
        self.assertIsNotNone(speech)
        self.assertLessEqual(abs(total - speech) / speech, 0.10)
        self.assertTrue(np.array_equal(chunks[0], big[:len(chunks[0])]))


if __name__ == "__main__":
    unittest.main()