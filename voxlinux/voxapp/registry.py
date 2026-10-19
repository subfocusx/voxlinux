"""
Catalog of speech-to-text models available to VoxLinux.

All models are official sherpa-onnx exports of GigaAM v3 (Russian), published
in the sherpa-onnx "asr-models" release:

    https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models

There are four variants, and they differ in two independent axes:

    * architecture — CTC (single model, greedy decode) vs RNN-T/transducer
      (encoder + decoder + joiner);
    * output — plain (letters only, 34 tokens) vs "punct" (punctuation,
      capitalisation and text normalisation baked into the model, 257 / 1025
      tokens).

Model ids and what they are good for:

    gigaam-v3-e2e-rnnt-punct   default. Best WER of the punctuation-aware
                              models (11.2 vs 12.0 for CTC) and the best
                              punctuation F1. ~+15% latency vs CTC.
    gigaam-v3-e2e-ctc-punct    same native punctuation at CTC speed. Use on
                              slow CPUs.
    gigaam-v3-rnnt-plain       no native punctuation (needs our heuristics),
                              but the only char-level transducer — the only
                              one where model-level hotwords work.
    gigaam-v3                  legacy plain CTC. Fallback / rollback.

Each entry describes:

    engine:               "sherpa-onnx"
    engine_subtype:       sherpa-onnx factory variant ("nemo-ctc" / "nemo-transducer")
    url:                  archive URL (tar.bz2 for sherpa-onnx)
    archive_format:       "tar.bz2"
    extracted_dir:        the top-level folder produced by extracting
                          the archive into the models dir
    files:                dict of relative paths inside extracted_dir,
                          named by the engine factory (see engines.py)
    needs_term_replace:   apply TERM_REPLACEMENTS post-processing
    needs_punctuation:    apply add_punctuation post-processing. False for
                          models that emit punctuation themselves — running
                          the heuristic on top of native punctuation
                          produces artefacts like "…зеленый,.".
"""

from __future__ import annotations

import os
from typing import Any

from voxapp.config import get_models_dir

_SHERPA_BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"

_GIGAAM_V3_CTC = "sherpa-onnx-nemo-ctc-giga-am-v3-russian-2025-12-16"
_GIGAAM_V3_CTC_PUNCT = "sherpa-onnx-nemo-ctc-punct-giga-am-v3-russian-2025-12-16"
_GIGAAM_V3_RNNT = "sherpa-onnx-nemo-transducer-giga-am-v3-russian-2025-12-16"
_GIGAAM_V3_RNNT_PUNCT = "sherpa-onnx-nemo-transducer-punct-giga-am-v3-russian-2025-12-16"

_RNNT_FILES = {
    "encoder": "encoder.int8.onnx",
    "decoder": "decoder.onnx",
    "joiner": "joiner.onnx",
    "tokens": "tokens.txt",
}

_CTC_FILES = {
    "model": "model.int8.onnx",
    "tokens": "tokens.txt",
}


MODELS: dict[str, dict[str, Any]] = {
    # ---------------- GigaAM v3, punctuation-aware ----------------
    "gigaam-v3-e2e-rnnt-punct": {
        "name": "GigaAM v3 e2e RNN-T (русский, с пунктуацией)",
        "engine": "sherpa-onnx",
        "engine_subtype": "nemo-transducer",
        "language": "ru",
        "size_mb": 162,
        "url": f"{_SHERPA_BASE}/{_GIGAAM_V3_RNNT_PUNCT}.tar.bz2",
        "archive_format": "tar.bz2",
        "extracted_dir": _GIGAAM_V3_RNNT_PUNCT,
        "files": dict(_RNNT_FILES),
        "needs_term_replace": True,
        "needs_punctuation": False,
        "description": (
            "GigaAM v3 от Сбера — end-to-end RNN-T с пунктуацией, регистром и "
            "нормализацией текста внутри модели (neMo transducer, sherpa-onnx). "
            "Лучший WER среди пунктуационных моделей: 11.2 против 12.0 у CTC."
        ),
    },
    "gigaam-v3-e2e-ctc-punct": {
        "name": "GigaAM v3 e2e CTC (русский, с пунктуацией)",
        "engine": "sherpa-onnx",
        "engine_subtype": "nemo-ctc",
        "language": "ru",
        "size_mb": 155,
        "url": f"{_SHERPA_BASE}/{_GIGAAM_V3_CTC_PUNCT}.tar.bz2",
        "archive_format": "tar.bz2",
        "extracted_dir": _GIGAAM_V3_CTC_PUNCT,
        "files": dict(_CTC_FILES),
        "needs_term_replace": True,
        "needs_punctuation": False,
        "description": (
            "То же, что RNN-T-вариант, но на CTC: та же нативная пунктуация и "
            "регистр при скорости обычного CTC. Для медленных CPU."
        ),
    },

    # ---------------- GigaAM v3, plain (letters only) ----------------
    "gigaam-v3-rnnt-plain": {
        "name": "GigaAM v3 RNN-T (русский, без пунктуации)",
        "engine": "sherpa-onnx",
        "engine_subtype": "nemo-transducer",
        "language": "ru",
        "size_mb": 159,
        "url": f"{_SHERPA_BASE}/{_GIGAAM_V3_RNNT}.tar.bz2",
        "archive_format": "tar.bz2",
        "extracted_dir": _GIGAAM_V3_RNNT,
        "files": dict(_RNNT_FILES),
        "needs_term_replace": True,
        "needs_punctuation": True,
        "description": (
            "Только буквы (34 токена) — пунктуацию добавляют наши эвристики. "
            "Единственная char-level модель: только с ней работают "
            "model-level hotwords (у punct-моделей BPE — падение sherpa-onnx)."
        ),
    },
    "gigaam-v3": {
        "name": "GigaAM v3 CTC (русский, legacy)",
        "engine": "sherpa-onnx",
        "engine_subtype": "nemo-ctc",
        "language": "ru",
        "size_mb": 155,
        "url": f"{_SHERPA_BASE}/{_GIGAAM_V3_CTC}.tar.bz2",
        "archive_format": "tar.bz2",
        "extracted_dir": _GIGAAM_V3_CTC,
        "files": dict(_CTC_FILES),
        "needs_term_replace": True,
        "needs_punctuation": True,
        "description": (
            "GigaAM v3 от Сбера — офлайн-модель распознавания русской речи "
            "(neMo CTC, sherpa-onnx). Только буквы, без пунктуации."
        ),
    },
}


DEFAULT_MODEL_ID = "gigaam-v3-e2e-rnnt-punct"
RECOMMENDED_MODEL_ID = "gigaam-v3-e2e-rnnt-punct"


def model_dir(model_id: str) -> str:
    """Absolute path where the model's extracted folder should live."""
    return os.path.join(get_models_dir(), MODELS[model_id]["extracted_dir"])


def is_installed(model_id: str) -> bool:
    """A model is installed if its extracted_dir exists on disk."""
    if model_id not in MODELS:
        return False
    return os.path.isdir(model_dir(model_id))


def resolved_files(model_id: str) -> dict[str, str]:
    """Return absolute paths for the model's files dict."""
    base = model_dir(model_id)
    return {key: os.path.join(base, rel) for key, rel in MODELS[model_id]["files"].items()}
