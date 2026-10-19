"""Unit tests for voxapp.itn (inverse text normalization)."""
from __future__ import annotations

import unittest

from voxapp.itn import apply_itn


class RussianItnTest(unittest.TestCase):
    def test_number_words_to_digits(self) -> None:
        self.assertEqual(
            apply_itn("сто двадцать три рубля", lang="ru"),
            "123 рубля",
        )

    def test_single_number_word(self) -> None:
        self.assertEqual(apply_itn("два сервера", lang="ru"), "2 сервера")

    def test_thousands(self) -> None:
        self.assertEqual(
            apply_itn("две тысячи триста сорок пять", lang="ru"),
            "2345",
        )

    def test_text_with_digits_left_alone(self) -> None:
        self.assertEqual(
            apply_itn("у меня 5 серверов", lang="ru"),
            "у меня 5 серверов",
        )

    def test_no_number_words_unchanged(self) -> None:
        text = "привет как дела"
        self.assertEqual(apply_itn(text, lang="ru"), text)


class DecimalBehaviourTest(unittest.TestCase):
    def test_current_decimal_spelling_behaviour(self) -> None:
        # The implementation has no special decimal handling ("целых" is not
        # a number word), so each number word converts independently and the
        # connector word is preserved. This pins the real behaviour.
        self.assertEqual(
            apply_itn("три целых пять", lang="ru"),
            "3 целых 5",
        )


class EnglishItnTest(unittest.TestCase):
    def test_english_number_words(self) -> None:
        self.assertEqual(
            apply_itn("twenty one servers", lang="en"),
            "21 servers",
        )

    def test_english_hundreds(self) -> None:
        self.assertEqual(
            apply_itn("one hundred twenty three", lang="en"),
            "123",
        )


class UnsupportedLanguageTest(unittest.TestCase):
    def test_unsupported_language_returns_text_unchanged(self) -> None:
        text = "два сервера"
        self.assertEqual(apply_itn(text, lang="de"), text)

    def test_empty_input(self) -> None:
        self.assertEqual(apply_itn("", lang="ru"), "")
        self.assertEqual(apply_itn("   ", lang="ru"), "   ")


if __name__ == "__main__":
    unittest.main()
