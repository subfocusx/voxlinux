"""Basic Russian/English question-mark and full-stop heuristics."""

from __future__ import annotations

import re

from voxapp.terms import TERM_REPLACEMENTS

QUESTION_WORDS = {
    "почему",
    "зачем",
    "как",
    "что",
    "где",
    "когда",
    "кто",
    "кого",
    "кому",
    "какой",
    "какая",
    "какое",
    "какие",
    "каким",
    "какую",
    "сколько",
    "который",
    "которая",
    "которое",
    "которые",
    "куда",
    "откуда",
    "отчего",
    "чей",
    "чья",
    "чьё",
    "чьи",
    "неужели",
    "разве",
    # English question words (phonetic)
    "вай",
    "хау",
    "вот",
    "вер",
    "вен",
    "ху",
    "хуз",
    "вич",
    "виз",
}

QUESTION_ENDINGS = {"да", "нет", "правда", "так", "ведь", "же"}
QUESTION_PARTICLES = {"ли", "разве", "неужели"}


def replace_terms(text: str) -> str:
    """Replace Russian phonetic transcriptions with English tech terms."""
    result = text
    for ru, en in TERM_REPLACEMENTS.items():
        pattern = re.compile(r"\b" + re.escape(ru) + r"\b", re.IGNORECASE)
        result = pattern.sub(en, result)
    return result


SENTENCE_ENDERS = ".?!…"
"""Characters that already close a sentence — nothing is appended after them."""

SOFT_ENDERS = ",;:"
"""Trailing marks that are left alone: a model (or a human) may end a
dictation with a comma; appending a period after it produced "…зеленый,."."""


def add_punctuation(text: str) -> str:
    """Capitalize first letter and add '.' or '?' at the end.

    Idempotent: text that already ends with a sentence terminator is returned
    unchanged (apart from the leading capital). A trailing soft mark
    (``,`` ``;`` ``:``) is left alone instead of being followed by a period.
    """
    if not text:
        return text

    text = text[0].upper() + text[1:] if len(text) > 1 else text.upper()

    stripped = text.rstrip()
    if not stripped:
        return text

    if stripped[-1] in SENTENCE_ENDERS or stripped[-1] in SOFT_ENDERS:
        return text

    words = text.lower().split()
    if not words:
        return text + "."

    first_word = words[0]
    last_word = words[-1]

    if first_word in QUESTION_WORDS:
        return text + "?"

    for word in words[:3]:
        if word in QUESTION_WORDS:
            return text + "?"

    for word in words:
        if word in QUESTION_PARTICLES:
            return text + "?"

    if last_word in QUESTION_ENDINGS:
        return text + "?"

    yes_no_starters = {
        "это",
        "а",
        "ну",
        "и",
        "теперь",
        "уже",
        "ещё",
        "еще",
        "всё",
        "все",
        "он",
        "она",
        "оно",
        "они",
        "ты",
        "вы",
        "мы",
    }
    if first_word in yes_no_starters and len(words) <= 6:
        verb_endings = (
            "ает",
            "яет",
            "ит",
            "ет",
            "ут",
            "ют",
            "ат",
            "ят",
            "ишь",
            "ешь",
            "ёшь",
            "ал",
            "ял",
            "ил",
            "ел",
            "али",
            "яли",
            "или",
            "ели",
            "ло",
            "ла",
            "ли",
            "ать",
            "ять",
            "ить",
            "еть",
            "оть",
            "уть",
            "ыть",
        )
        for word in words:
            if word.endswith(verb_endings):
                return text + "?"

    return text + "."
