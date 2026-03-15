"""Unit tests for calibration.py — no phone required."""

import json
from pathlib import Path

import pytest

from wechat_moments.calibration import UIProfile, load_profile, save_profile


def test_default_profile_returned_when_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("wechat_moments.calibration.PROFILES_DIR", tmp_path)
    profile = load_profile("unknown_device_xyz")
    assert profile.device_id == "unknown_device_xyz"
    assert profile.screen_width == 1080


def test_huawei_default_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("wechat_moments.calibration.PROFILES_DIR", tmp_path)
    default = {"screen_width": 1080, "screen_height": 2400, "tab_bar_y": 2280}
    (tmp_path / "huawei_default.json").write_text(json.dumps(default))

    profile = load_profile("some_other_device")
    assert profile.screen_height == 2400
    assert profile.tab_bar_y == 2280


def test_save_and_reload_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("wechat_moments.calibration.PROFILES_DIR", tmp_path)

    profile = UIProfile(device_id="test123", screen_width=1440, screen_height=3200)
    save_profile(profile)

    loaded = load_profile("test123")
    assert loaded.screen_width == 1440
    assert loaded.screen_height == 3200


def test_tab_coords() -> None:
    p = UIProfile(device_id="test", screen_width=1080, screen_height=2340, tab_bar_y=2200)
    # Tab 2 (发现) should be in the third quarter
    x, y = p.tab_coords(2)
    assert 500 < x < 800
    assert y == 2200


def test_album_cell_coords_row_major() -> None:
    p = UIProfile(
        device_id="test",
        screen_width=1080,
        screen_height=2340,
        album_grid_first_x=100,
        album_grid_first_y=200,
        album_grid_col_width=250,
        album_grid_row_height=250,
    )
    x0, y0 = p.album_cell_coords(0)
    x1, y1 = p.album_cell_coords(1)
    x4, y4 = p.album_cell_coords(4)  # Second row, first column (4 columns)

    # Second cell should be to the right of first
    assert x1 > x0
    assert x1 == x0 + 250  # col_width

    # Fifth cell (index 4) should be on second row
    assert y4 > y0
    assert y4 == y0 + 250  # row_height
    assert x4 == x0  # Same column as first
