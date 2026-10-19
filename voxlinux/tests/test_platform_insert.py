"""Unit tests for text insertion in voxapp.platform_linux (no real typing)."""
from __future__ import annotations

import io
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

import voxapp.platform_linux as platform


class TypeTextTest(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_wtype = platform.Tools.wtype
        self._saved_ydotool = platform.Tools.ydotool
        platform.Tools.wtype = "/fake/wtype"
        platform.Tools.ydotool = "/fake/ydotool"

    def tearDown(self) -> None:
        platform.Tools.wtype = self._saved_wtype
        platform.Tools.ydotool = self._saved_ydotool

    def test_empty_text_returns_zero_without_subprocess(self):
        with patch("voxapp.platform_linux.subprocess.run") as run, patch(
            "voxapp.platform_linux.subprocess.Popen"
        ) as popen:
            rc = platform.type_text("")
        self.assertEqual(rc, 0)
        run.assert_not_called()
        popen.assert_not_called()

    def test_wtype_success_does_not_call_ydotool(self):
        # Clipboard paste succeeds on the first wtype invocation.
        with patch("voxapp.platform_linux.which", return_value="/fake/wl-copy"), patch(
            "voxapp.platform_linux.subprocess.Popen"
        ) as popen, patch("voxapp.platform_linux.subprocess.run") as run:
            popen.return_value.communicate.return_value = (None, None)
            run.return_value = MagicMock(returncode=0, stderr="")
            rc = platform.type_text("hello")
        self.assertEqual(rc, 0)
        # ydotool must never have been invoked.
        for call in run.call_args_list:
            argv = call.args[0] if call.args else call.kwargs.get("args")
            self.assertNotIn("/fake/ydotool", argv)

    def test_wtype_direct_success_does_not_call_ydotool(self):
        # No wl-copy available: direct wtype succeeds.
        with patch("voxapp.platform_linux.which", return_value=None), patch(
            "voxapp.platform_linux.subprocess.run"
        ) as run:
            run.return_value = MagicMock(returncode=0, stderr="")
            rc = platform.type_text("hello")
        self.assertEqual(rc, 0)
        self.assertEqual(run.call_count, 1)
        argv = run.call_args_list[0].args[0]
        self.assertEqual(argv, ["/fake/wtype", "--", "hello"])

    def test_wtype_failure_calls_ydotool_with_right_argv(self):
        with patch("voxapp.platform_linux.which", return_value="/fake/wl-copy"), patch(
            "voxapp.platform_linux.subprocess.Popen"
        ) as popen, patch("voxapp.platform_linux.subprocess.run") as run:
            popen.return_value.communicate.return_value = (None, None)
            run.side_effect = [
                MagicMock(returncode=1, stderr="paste fail"),   # clipboard paste
                MagicMock(returncode=1, stderr="direct fail"),  # direct wtype
                MagicMock(returncode=0, stderr=""),             # ydotool
            ]
            rc = platform.type_text("hello")
        self.assertEqual(rc, 0)
        # last invocation is ydotool with the expected argv
        last_argv = run.call_args_list[-1].args[0]
        self.assertEqual(
            last_argv, ["/fake/ydotool", "type", "--delay", "20", "--", "hello"]
        )

    def test_wtype_missing_calls_ydotool(self):
        platform.Tools.wtype = None
        with patch("voxapp.platform_linux.which", return_value=None), patch(
            "voxapp.platform_linux.subprocess.run"
        ) as run:
            run.return_value = MagicMock(returncode=0, stderr="")
            rc = platform.type_text("hello")
        self.assertEqual(rc, 0)
        self.assertEqual(
            run.call_args_list[-1].args[0],
            ["/fake/ydotool", "type", "--delay", "20", "--", "hello"],
        )

    def test_both_fail_returns_nonzero_and_mentions_ydotool(self):
        with patch("voxapp.platform_linux.which", return_value="/fake/wl-copy"), patch(
            "voxapp.platform_linux.subprocess.Popen"
        ) as popen, patch("voxapp.platform_linux.subprocess.run") as run:
            popen.return_value.communicate.return_value = (None, None)
            run.side_effect = [
                MagicMock(returncode=1, stderr="paste fail"),
                MagicMock(returncode=1, stderr="direct fail"),
                MagicMock(returncode=2, stderr="ydotool fail"),
            ]
            buf = io.StringIO()
            with patch.object(sys, "stderr", buf):
                rc = platform.type_text("hello")
        self.assertNotEqual(rc, 0)
        self.assertIn("ydotool", buf.getvalue())

    def test_leading_dash_passed_after_double_dash(self):
        platform.Tools.wtype = "/fake/wtype"
        with patch("voxapp.platform_linux.which", return_value=None), patch(
            "voxapp.platform_linux.subprocess.run"
        ) as run:
            run.side_effect = [
                MagicMock(returncode=1, stderr="direct fail"),
                MagicMock(returncode=0, stderr=""),
            ]
            rc = platform.type_text("-evil")
        self.assertEqual(rc, 0)
        last_argv = run.call_args_list[-1].args[0]
        self.assertEqual(last_argv[-2:], ["--", "-evil"])
        first_argv = run.call_args_list[0].args[0]
        self.assertIn("--", first_argv)
        self.assertEqual(first_argv[-1], "-evil")

    def test_tools_detect_includes_ydotool(self):
        with patch("voxapp.platform_linux.which") as w:
            w.side_effect = lambda name: f"/fake/{name}" if name in ("wtype", "ydotool") else None
            result = platform.Tools.detect()
        self.assertIn("ydotool", result)
        self.assertEqual(platform.Tools.ydotool, "/fake/ydotool")
        # restore detection to real environment
        platform.Tools.detect()


if __name__ == "__main__":
    unittest.main()
