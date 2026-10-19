"""Unit tests for the voxapp.post_processor pipeline."""
from __future__ import annotations

import unittest

from voxapp.post_processor import PostProcessor


def _plain(**kwargs) -> PostProcessor:
    """PostProcessor with cursor-dependent steps off for deterministic tests."""
    kwargs.setdefault("enable_capitalization", False)
    kwargs.setdefault("enable_spacing", False)
    kwargs.setdefault("always_leading_space", False)
    return PostProcessor(**kwargs)


class PipelineCompositionTest(unittest.TestCase):
    def test_full_pipeline_ru(self) -> None:
        pp = _plain(lang="ru")
        out = pp.process_text("эээ мне нужно пять серверов на реакт")
        self.assertIn("5", out)
        self.assertIn("React", out)
        self.assertNotIn("эээ", out)
        self.assertTrue(out.endswith((".", "?", "!", ",", ";", ":", "»", "…")))

    def test_empty_and_whitespace_passthrough(self) -> None:
        pp = _plain()
        self.assertEqual(pp.process_text(""), "")
        self.assertEqual(pp.process_text("   "), "   ")

    def test_steps_recorded(self) -> None:
        pp = _plain(lang="ru")
        result = pp.process("пять серверов")
        self.assertIn("itn", result.steps)
        self.assertIn("punctuation", result.steps)
        self.assertEqual(result.processed, result.steps["punctuation"])


class StepToggleTest(unittest.TestCase):
    def test_disable_terms(self) -> None:
        pp = _plain(enable_terms=False)
        out = pp.process_text("напиши на реакт")
        self.assertIn("реакт", out)
        self.assertNotIn("React", out)

    def test_disable_fillers(self) -> None:
        pp = _plain(enable_fillers=False)
        out = pp.process_text("ээ привет")
        self.assertIn("ээ", out.lower())

    def test_disable_itn(self) -> None:
        pp = _plain(enable_itn=False)
        out = pp.process_text("пять серверов")
        self.assertIn("пять", out.lower())
        self.assertNotIn("5", out)

    def test_disable_punctuation(self) -> None:
        pp = _plain(enable_punctuation=False)
        out = pp.process_text("привет")
        self.assertFalse(out.endswith("."))
        self.assertIn("привет", out.lower())

    def test_disable_sentence_spacing(self) -> None:
        pp = _plain(enable_sentence_spacing=False)
        result = pp.process("Привет.Что")
        self.assertNotIn("sentence_spacing", result.steps)


class FromModelConfigTest(unittest.TestCase):
    def test_honours_registry_flags_false(self) -> None:
        info = {"language": "ru", "needs_term_replace": False, "needs_punctuation": False}
        pp = PostProcessor.from_model_config(info)
        self.assertFalse(pp.enable_terms)
        self.assertFalse(pp.enable_punctuation)
        self.assertTrue(pp.enable_fillers)
        self.assertTrue(pp.enable_itn)
        self.assertEqual(pp.lang, "ru")

    def test_honours_registry_flags_true(self) -> None:
        info = {"language": "ru", "needs_term_replace": True, "needs_punctuation": True}
        pp = PostProcessor.from_model_config(info)
        self.assertTrue(pp.enable_terms)
        self.assertTrue(pp.enable_punctuation)

    def test_multi_language_falls_back_to_ru(self) -> None:
        info = {"language": "multi", "needs_term_replace": True, "needs_punctuation": True}
        pp = PostProcessor.from_model_config(info)
        self.assertEqual(pp.lang, "ru")

    def test_lang_override(self) -> None:
        info = {"language": "ru", "needs_term_replace": True, "needs_punctuation": True}
        pp = PostProcessor.from_model_config(info, lang="en")
        self.assertEqual(pp.lang, "en")

    def test_disabled_punctuation_end_to_end(self) -> None:
        info = {"language": "ru", "needs_term_replace": True, "needs_punctuation": False}
        pp = PostProcessor.from_model_config(
            info, lang="ru",
        )
        pp.enable_capitalization = False
        pp.enable_spacing = False
        pp.always_leading_space = False
        out = pp.process_text("привет")
        self.assertFalse(out.endswith("."))


class ModelAwarePunctuationTest(unittest.TestCase):
    """Model-aware punctuation behaviour driven by needs_punctuation."""

    def _make(self, needs_punctuation: bool) -> PostProcessor:
        pp = PostProcessor.from_model_config(
            {"language": "ru", "needs_punctuation": needs_punctuation}
        )
        # Isolate the punctuation/ITN behaviour from cursor-dependent steps.
        pp.enable_capitalization = False
        pp.enable_spacing = False
        pp.always_leading_space = False
        return pp

    def test_native_punctuation_passes_through_unchanged(self) -> None:
        pp = self._make(False)
        out = pp.process_text("Привет! Сегодня релиз.")
        self.assertEqual(out, "Привет! Сегодня релиз.")
        self.assertFalse(out.endswith(",."))

    def test_heuristic_applied_when_needed(self) -> None:
        pp = self._make(True)
        out = pp.process_text("привет")
        self.assertEqual(out, "Привет.")

    def test_itn_still_applies_when_punctuation_disabled(self) -> None:
        pp = self._make(False)
        out = pp.process_text("Мне нужно пять серверов.")
        self.assertEqual(out, "Мне нужно 5 серверов.")


if __name__ == "__main__":
    unittest.main()
