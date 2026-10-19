"""Unit tests for the dictation history wiring (storage + daemon path)."""
from __future__ import annotations

import os
import tempfile
import unittest

from voxapp.storage import VoxDB
from voxapp.daemon import DictationDaemon


class StorageHistoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "vox_data.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_dictation_writes_row(self) -> None:
        db = VoxDB(self.db_path)
        try:
            row_id = db.add_transcription("raw text", "processed text", model="m", duration_ms=1200)
            self.assertTrue(isinstance(row_id, int))
            self.assertEqual(db.count_transcriptions(), 1)
            entries = db.get_history(limit=10)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].raw_text, "raw text")
            self.assertEqual(entries[0].processed_text, "processed text")
            self.assertEqual(entries[0].duration_ms, 1200)
        finally:
            db.close()

    def test_history_n_newest_order(self) -> None:
        db = VoxDB(self.db_path)
        try:
            for i in range(5):
                db.add_transcription(f"text {i}", duration_ms=i * 100)
            # newest first
            entries = db.get_history(limit=3)
            self.assertEqual(len(entries), 3)
            self.assertEqual(entries[0].raw_text, "text 4")
            self.assertEqual(entries[1].raw_text, "text 3")
            self.assertEqual(entries[2].raw_text, "text 2")
            # at most N
            self.assertLessEqual(len(db.get_history(limit=10)), 10)
        finally:
            db.close()

    def test_stats_returns_dict(self) -> None:
        db = VoxDB(self.db_path)
        try:
            db.add_transcription("a", duration_ms=100)
            stats = db.get_stats()
            self.assertIsInstance(stats, dict)
            self.assertIn("total_transcriptions", stats)
            self.assertEqual(stats["total_transcriptions"], 1)
        finally:
            db.close()

    def test_db_path_keyword(self) -> None:
        db = VoxDB(db_path=self.db_path)
        try:
            self.assertEqual(db.path, self.db_path)
        finally:
            db.close()


class DaemonHistoryPathTest(unittest.TestCase):
    def test_storage_failure_does_not_propagate(self) -> None:
        # Point at an unwritable path: parent is a file.
        tmp = tempfile.TemporaryDirectory()
        try:
            blocker = os.path.join(tmp.name, "notadir")
            with open(blocker, "w") as f:
                f.write("x")
            bad_path = os.path.join(blocker, "vox_data.db")
            daemon = DictationDaemon(db_path=bad_path, model_id=None)
            # model_id may be invalid if no models; force None path still ok
            # store must swallow
            daemon._store_transcription("hello", "hello", duration_ms=500)
            # history read must also not raise and return empty-ish
            res = daemon._history(limit=5)
            self.assertEqual(res, [])
            stats = daemon._stats()
            self.assertEqual(stats, {})
        finally:
            try:
                daemon.shutdown()
            except Exception:
                pass
            tmp.cleanup()

    def test_daemon_round_trip_storage(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            db_path = os.path.join(tmp.name, "vox_data.db")
            daemon = DictationDaemon(db_path=db_path, model_id=None)
            daemon._store_transcription("raw hi", "processed hi", duration_ms=321)
            # read back through same code path the control socket uses
            text = daemon._history_text(10)
            self.assertIn("processed hi", text)
            self.assertIn("0.3s", text)
            stats_text = daemon._stats_text()
            self.assertIn("total_transcriptions: 1", stats_text)
            # and structured
            entries = daemon._history(limit=10)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].processed_text, "processed hi")
            s = daemon._stats()
            self.assertIsInstance(s, dict)
            self.assertEqual(s["total_transcriptions"], 1)
        finally:
            try:
                daemon.shutdown()
            except Exception:
                pass
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()