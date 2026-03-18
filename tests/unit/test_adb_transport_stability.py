"""Tests for ADB transport stability improvements.

Covers:
1. screenshot() uses a single combined shell command (screencap && base64)
   instead of two separate ADB calls, halving USB round-trips.
2. CLI post command restarts ADB server after posting to prevent stale
   transport on Honor/Huawei devices.
3. OCR crop region in extract_moments_feed_top_text covers the actual
   post content area (18-55% height) instead of the cover photo (8-40%).
"""

import base64
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# 1. screenshot() single-command test
# ---------------------------------------------------------------------------


class TestScreenshotSingleCommand:
    """Verify screenshot() issues a single ``adb shell`` invocation."""

    @patch("wechat_moments.adb.ADB._get_display_id", return_value=None)
    @patch("wechat_moments.adb.ADB.get_serial")
    @patch("wechat_moments.adb.ADB._run")
    def test_single_shell_call(self, mock_run, mock_serial, mock_display):
        """screenshot() must call _run exactly once on success (single round-trip)."""
        from wechat_moments.adb import ADB

        # Fake a minimal valid PNG (8-byte signature + enough padding)
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
        fake_b64 = base64.b64encode(fake_png).decode()

        mock_run.return_value = MagicMock(
            returncode=0, stdout=fake_b64
        )

        adb = ADB.__new__(ADB)
        adb._base = ["adb"]
        adb._serial = "FAKE"
        adb._lock = __import__("threading").Lock()
        adb._display_id = None

        result = adb.screenshot()

        # Must be exactly 1 _run call (not 2)
        assert mock_run.call_count == 1, (
            f"Expected 1 _run call (combined command), got {mock_run.call_count}"
        )

        # The single call must be a shell command containing both screencap AND base64
        args = mock_run.call_args[0][0]
        assert args[0] == "shell"
        shell_cmd = args[1]
        assert "screencap" in shell_cmd
        assert "base64" in shell_cmd
        assert "&&" in shell_cmd

        # Returned data is the decoded PNG
        assert result == fake_png

    @patch("wechat_moments.adb.ADB._get_display_id", return_value="0")
    @patch("wechat_moments.adb.ADB.get_serial")
    @patch("wechat_moments.adb.ADB._run")
    def test_display_id_included_in_combined_cmd(self, mock_run, mock_serial, mock_display):
        """When display_id is available, the combined command includes -d flag."""
        from wechat_moments.adb import ADB

        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
        mock_run.return_value = MagicMock(
            returncode=0, stdout=base64.b64encode(fake_png).decode()
        )

        adb = ADB.__new__(ADB)
        adb._base = ["adb"]
        adb._serial = "FAKE"
        adb._lock = __import__("threading").Lock()
        adb._display_id = "0"

        adb.screenshot()

        shell_cmd = mock_run.call_args[0][0][1]
        assert "-d 0" in shell_cmd or "-d0" in shell_cmd

    @patch("wechat_moments.adb.ADB.restart_server")
    @patch("wechat_moments.adb.ADB._get_display_id", return_value=None)
    @patch("wechat_moments.adb.ADB.get_serial")
    @patch("wechat_moments.adb.ADB._run")
    def test_retries_and_restarts_server(self, mock_run, mock_serial, mock_display, mock_restart):
        """After 3 failures, screenshot() restarts ADB server and retries."""
        from wechat_moments.adb import ADB

        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200

        # Fail 3 times, succeed on 4th (after server restart)
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout=""),
            MagicMock(returncode=1, stdout=""),
            MagicMock(returncode=1, stdout=""),
            MagicMock(returncode=0, stdout=base64.b64encode(fake_png).decode()),
        ]

        adb = ADB.__new__(ADB)
        adb._base = ["adb"]
        adb._serial = "FAKE"
        adb._lock = __import__("threading").Lock()
        adb._display_id = None

        result = adb.screenshot()

        assert mock_restart.call_count == 1
        assert result == fake_png


# ---------------------------------------------------------------------------
# 2. CLI post restart_server test
# ---------------------------------------------------------------------------


class TestPostRestartsServer:
    """Verify the post CLI command calls restart_server after posting."""

    def test_cli_py_contains_restart_server_call(self):
        """cli.py must contain a restart_server() call after the post result handling."""
        cli_path = Path(__file__).parent.parent.parent / "src" / "wechat_moments" / "cli.py"
        code = cli_path.read_text()

        # The restart_server call should appear after the result status check
        result_idx = code.find("Posted successfully")
        restart_idx = code.find("restart_server()")

        assert restart_idx != -1, "restart_server() not found in cli.py"
        assert restart_idx > result_idx, (
            "restart_server() should appear after 'Posted successfully' handling"
        )


# ---------------------------------------------------------------------------
# 3. OCR crop region test
# ---------------------------------------------------------------------------


class TestOcrCropRegion:
    """Verify extract_moments_feed_top_text uses correct crop coordinates."""

    def test_crop_region_below_cover_photo(self):
        """OCR crop must start at ≥15% height (below cover photo) not 8%."""
        import inspect

        from wechat_moments.cv import extract_moments_feed_top_text

        source = inspect.getsource(extract_moments_feed_top_text)

        # Must NOT contain the old 0.08 crop start
        assert "0.08" not in source, (
            "OCR crop still uses 0.08 (8%) which includes the cover photo area"
        )

        # Must use a start ≥ 0.15
        # Check that the y1 assignment uses a value >= 0.15
        assert "0.18" in source or "0.15" in source or "0.20" in source, (
            "OCR crop y1 should start at 15-20% to skip the cover photo"
        )

        # Must NOT use the old narrow x range (0.10)
        # The function should use 0.05 for wider capture
        assert "0.05" in source, (
            "OCR crop x1 should be 0.05 (5%) for wider text capture"
        )
