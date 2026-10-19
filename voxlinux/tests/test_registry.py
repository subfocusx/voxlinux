"""Structural unit tests for voxapp.registry (model-list agnostic)."""
from __future__ import annotations

import os
import unittest

from voxapp import registry
from voxapp.config import get_models_dir


REQUIRED_KEYS = frozenset(
    {
        "name",
        "engine",
        "engine_subtype",
        "language",
        "size_mb",
        "url",
        "archive_format",
        "extracted_dir",
        "files",
        "needs_term_replace",
        "needs_punctuation",
        "description",
    }
)


class ModelsStructureTest(unittest.TestCase):
    def test_models_non_empty(self) -> None:
        self.assertTrue(registry.MODELS)

    def test_every_entry_has_required_keys(self) -> None:
        for model_id, entry in registry.MODELS.items():
            with self.subTest(model_id=model_id):
                self.assertTrue(
                    REQUIRED_KEYS.issubset(entry.keys()),
                    f"{model_id} missing keys: {REQUIRED_KEYS - set(entry.keys())}",
                )

    def test_files_values_are_relative_paths(self) -> None:
        for model_id, entry in registry.MODELS.items():
            with self.subTest(model_id=model_id):
                self.assertIsInstance(entry["files"], dict)
                self.assertTrue(entry["files"])
                for key, rel in entry["files"].items():
                    self.assertIsInstance(rel, str, f"{model_id}.files[{key}]")
                    self.assertFalse(
                        os.path.isabs(rel), f"{model_id}.files[{key}] must be relative"
                    )
                    inner = os.path.join(entry["extracted_dir"], rel)
                    self.assertNotIn("..", inner.split(os.sep))

    def test_resolved_files_stay_inside_extracted_dir(self) -> None:
        for model_id in registry.MODELS:
            with self.subTest(model_id=model_id):
                base = registry.model_dir(model_id)
                for key, abs_path in registry.resolved_files(model_id).items():
                    self.assertEqual(
                        os.path.commonpath([base, abs_path]),
                        base,
                        f"{model_id}.files[{key}] escapes extracted_dir",
                    )

    def test_url_matches_archive_format(self) -> None:
        for model_id, entry in registry.MODELS.items():
            with self.subTest(model_id=model_id):
                fmt = entry["archive_format"]
                url = entry["url"]
                if fmt == "tar.bz2":
                    self.assertTrue(url.endswith(".tar.bz2"), url)
                elif fmt == "zip":
                    self.assertTrue(url.endswith(".zip"), url)
                else:
                    self.fail(f"{model_id}: unknown archive_format {fmt!r}")

    def test_model_dir_inside_models_root(self) -> None:
        root = os.path.realpath(get_models_dir())
        for model_id in registry.MODELS:
            with self.subTest(model_id=model_id):
                path = os.path.realpath(registry.model_dir(model_id))
                self.assertEqual(os.path.commonpath([root, path]), root)


class InstalledCheckTest(unittest.TestCase):
    def test_unknown_id_returns_false_without_raising(self) -> None:
        self.assertFalse(registry.is_installed("no-such-model-xyz"))

    def test_known_ids_return_bool(self) -> None:
        for model_id in registry.MODELS:
            with self.subTest(model_id=model_id):
                self.assertIsInstance(registry.is_installed(model_id), bool)


class ModelInvariantsTest(unittest.TestCase):
    def test_at_least_one_native_and_one_heuristic(self) -> None:
        flags = {entry["needs_punctuation"] for entry in registry.MODELS.values()}
        self.assertIn(False, flags)
        self.assertIn(True, flags)

    def test_default_model_id_exists(self) -> None:
        self.assertIn(registry.DEFAULT_MODEL_ID, registry.MODELS)

    def test_engine_subtype_supported(self) -> None:
        supported = {"nemo-ctc", "nemo-transducer"}
        for model_id, entry in registry.MODELS.items():
            with self.subTest(model_id=model_id):
                self.assertIn(entry["engine_subtype"], supported)

    def test_files_keys_match_engine_branch(self) -> None:
        ctc_keys = {"model", "tokens"}
        transducer_keys = {"encoder", "decoder", "joiner", "tokens"}
        for model_id, entry in registry.MODELS.items():
            with self.subTest(model_id=model_id):
                if entry["engine_subtype"] == "nemo-ctc":
                    self.assertEqual(set(entry["files"].keys()), ctc_keys)
                elif entry["engine_subtype"] == "nemo-transducer":
                    self.assertEqual(set(entry["files"].keys()), transducer_keys)
                else:
                    self.fail(f"unknown subtype {entry['engine_subtype']!r}")


if __name__ == "__main__":
    unittest.main()
