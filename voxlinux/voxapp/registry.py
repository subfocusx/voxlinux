"""
Catalog of speech-to-text models available to VoxLinux.

Only one model is supported: GigaAM v3 (Russian), sherpa-onnx neMo CTC.

Each entry describes:

    engine:               "sherpa-onnx"
    engine_subtype:       sherpa-onnx factory variant ("nemo-ctc")
    url:                  archive URL (tar.bz2 for sherpa-onnx)
    archive_format:       "tar.bz2"
    extracted_dir:        the top-level folder produced by extracting
                          the archive into the models dir
    files:                dict of relative paths inside extracted_dir,
                          named by the engine factory (see engines.py)
    needs_term_replace:   apply TERM_REPLACEMENTS post-processing
    needs_punctuation:    apply add_punctuation post-processing
"""

from __future__ import annotations

import os
from typing import Any

from voxapp.config import get_models_dir

_SHERPA_BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"
_GIGAAM_V3 = "sherpa-onnx-nemo-ctc-giga-am-v3-russian-2025-12-16"


MODELS: dict[str, dict[str, Any]] = {
    # ---------------- GigaAM v3 (Russian) — the only model ----------------
    "gigaam-v3": {
        "name": "GigaAM v3 (русский)",
        "engine": "sherpa-onnx",
        "engine_subtype": "nemo-ctc",
        "language": "ru",
        "size_mb": 163,
        "url": f"{_SHERPA_BASE}/{_GIGAAM_V3}.tar.bz2",
        "archive_format": "tar.bz2",
        "extracted_dir": _GIGAAM_V3,
        "files": {
            "model": "model.int8.onnx",
            "tokens": "tokens.txt",
        },
        "needs_term_replace": True,
        "needs_punctuation": True,
        "description": (
            "GigaAM v3 от Сбера — офлайн-модель распознавания русской речи "
            "(neMo CTC, sherpa-onnx)."
        ),
    },
}


DEFAULT_MODEL_ID = "gigaam-v3"
RECOMMENDED_MODEL_ID = "gigaam-v3"


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