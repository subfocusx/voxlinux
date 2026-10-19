"""Unit tests for voxapp.punctuation heuristics and term replacement."""
from __future__ import annotations

import unittest

from voxapp.punctuation import add_punctuation, replace_terms


class AddPunctuationTest(unittest.TestCase):
    def test_adds_final_period(self) -> None:
        self.assertEqual(add_punctuation("привет"), "Привет.")

    def test_idempotent_period(self) -> None:
        self.assertEqual(add_punctuation("Привет."), "Привет.")

    def test_idempotent_exclamation(self) -> None:
        self.assertEqual(add_punctuation("Привет!"), "Привет!")

    def test_idempotent_question(self) -> None:
        self.assertEqual(add_punctuation("Как дела?"), "Как дела?")

    def test_question_word_gets_question_mark(self) -> None:
        self.assertEqual(add_punctuation("как дела"), "Как дела?")

    def test_trailing_comma_gets_no_period(self) -> None:
        # A trailing comma is a soft continuation mark: no period appended.
        self.assertEqual(
            add_punctuation("У лукоморья дуб зелёный,"),
            "У лукоморья дуб зелёный,",
        )

    def test_trailing_semicolon_gets_no_period(self) -> None:
        # Genuinely trailing soft mark: nothing appended.
        self.assertEqual(add_punctuation("первое;"), "Первое;")
        self.assertEqual(add_punctuation("текст:"), "Текст:")

    def test_trailing_colon_gets_no_period(self) -> None:
        out = add_punctuation("текст:")
        self.assertFalse(out.endswith(":."))
        self.assertTrue(out.startswith("Текст"))
        self.assertEqual(add_punctuation("текст:"), "Текст:")

    def test_mid_text_soft_mark_gets_final_period(self) -> None:
        # A soft mark in the MIDDLE of the text does NOT suppress the final
        # period: the terminator is still appended after the last word.
        self.assertEqual(add_punctuation("первое; второе"), "Первое; второе.")

    def test_trailing_ellipsis_gets_no_period(self) -> None:
        out = add_punctuation("ну так…")
        self.assertFalse(out.endswith("…."))
        self.assertTrue(out.endswith("…"))
        self.assertEqual(add_punctuation("ну так…"), "Ну так…")

    def test_empty_input_unchanged(self) -> None:
        self.assertEqual(add_punctuation(""), "")

    def test_whitespace_only_unchanged(self) -> None:
        for text in ("   ", "\t", "\n  "):
            self.assertEqual(add_punctuation(text), text)


class ReplaceTermsTest(unittest.TestCase):
    def test_replaces_known_phonetic_term(self) -> None:
        out = replace_terms("напиши на реакт")
        self.assertIn("React", out)
        self.assertNotIn("реакт", out.lower())

    def test_leaves_unknown_text_alone(self) -> None:
        text = "обычный текст без терминов"
        self.assertEqual(replace_terms(text), text)

    def test_empty_input(self) -> None:
        self.assertEqual(replace_terms(""), "")


if __name__ == "__main__":
    unittest.main()
