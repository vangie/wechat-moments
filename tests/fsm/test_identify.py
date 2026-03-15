"""FSM state identify() tests using real screenshots — no phone required.

Two fixture sources:
- Recorded: one dir per step (P1S01_..., P2S01_..., etc.) with screenshot.png; keep as-is.
- Supplement: fixtures/supplement/<state>/01.png, 02.png, ...
  - <state> in SUPPLEMENT_STATE_MAP: extra images for that state (e.g. moments_feed/).
  - other/: 其他页面 — must not be identified as compose (INPUT_TEXT). No duplication of recorded files.
"""

from pathlib import Path

import pytest

from wechat_moments.poster import PlanState, UiState, _identify_state

FIXTURES = Path(__file__).parent / "fixtures"
SUPPLEMENT = FIXTURES / "supplement"


def _screenshot_bytes(fixture_dir: str) -> bytes:
    """Load screenshot.png from a recorded fixture directory."""
    path = FIXTURES / fixture_dir / "screenshot.png"
    if not path.exists():
        pytest.skip(f"Fixture screenshot not found: {path}")
    return path.read_bytes()


def _screenshot_bytes_supplement(state_dir: str, filename: str) -> bytes:
    """Load screenshot from supplement (e.g. supplement/moments_feed/01.png)."""
    path = SUPPLEMENT / state_dir / filename
    if not path.exists():
        pytest.skip(f"Supplement not found: {path}")
    return path.read_bytes()


# --- Recorded fixtures: directory name → expected UiState ---
FIXTURE_STATE_MAP = {
    "P1S01_wait_wechat_main_screen": UiState.WECHAT_MAIN,
    "P1S02_tap_tap_discover_tab": UiState.WECHAT_MAIN,
    "P1S03_tap_tap_moments_entry": UiState.DISCOVER_PAGE,
    "P2S01_tap_tap_camera_button": UiState.MOMENTS_FEED,
    "P2S02_tap_tap_album_option": UiState.CAMERA_BOTTOM_SHEET,
    "P2S03_tap_tap_album_dropdown": UiState.ALBUM_PICKER,
    "P2S04_tap_select_wechatmcp_album": UiState.ALBUM_DROPDOWN,
    "P2S05_tap_select_image_1__row1_col1_": UiState.ALBUM_PICKER,
    "P2S06_tap_select_image_5__row2_col1_": UiState.ALBUM_PICKER,
    "P2S07_tap_select_image_6__row2_col2_": UiState.ALBUM_PICKER,
    "P2S08_tap_tap_done_button": UiState.ALBUM_PICKER,
    "P2S09_tap_tap_text_area": UiState.INPUT_TEXT,
    "P2S10_wait_text_input_complete": UiState.INPUT_TEXT,
    "P2S11_tap_tap_back_button": UiState.INPUT_TEXT,
    "P2S12_tap_tap_discard_button": UiState.DISCARD_DIALOG,
    "P3S01_long_press_long_press_camera": UiState.MOMENTS_FEED,
    "P3S02_tap_tap_text_area": UiState.INPUT_TEXT,
    "P3S03_wait_text_input_complete": UiState.INPUT_TEXT,
    "P3S04_tap_tap_back_button": UiState.INPUT_TEXT,
    "P3S05_tap_tap_discard_button": UiState.DISCARD_DIALOG,
}

# Supplement: state dir name (under supplement/) → UiState
SUPPLEMENT_STATE_MAP = {
    "moments_feed": UiState.MOMENTS_FEED,
    "wechat_main": UiState.WECHAT_MAIN,
    "discover_page": UiState.DISCOVER_PAGE,
    "camera_bottom_sheet": UiState.CAMERA_BOTTOM_SHEET,
    "album_picker": UiState.ALBUM_PICKER,
    "album_dropdown": UiState.ALBUM_DROPDOWN,
    "input_text": UiState.INPUT_TEXT,
    "discard_dialog": UiState.DISCARD_DIALOG,
}


def _list_supplement_fixtures() -> list[tuple[str, str, UiState]]:
    """List (state_dir, filename, expected_state) for every image under supplement/<state>/."""
    out: list[tuple[str, str, UiState]] = []
    if not SUPPLEMENT.is_dir():
        return out
    for state_dir in sorted(SUPPLEMENT.iterdir()):
        if not state_dir.is_dir():
            continue
        state_name = state_dir.name
        if state_name not in SUPPLEMENT_STATE_MAP:
            continue
        expected = SUPPLEMENT_STATE_MAP[state_name]
        for p in sorted(state_dir.glob("*.png")):
            out.append((state_name, p.name, expected))
    return out


def _list_other_fixtures() -> list[tuple[str, str]]:
    """List (state_dir, filename) for supplement/other/*.png (其他页面, must not be identified as compose)."""
    out: list[tuple[str, str]] = []
    other_dir = SUPPLEMENT / "other"
    if not other_dir.is_dir():
        return out
    for p in sorted(other_dir.glob("*.png")):
        out.append(("other", p.name))
    return out


def _identify_fixture_ids() -> list[tuple[str, UiState]]:
    """All fixture ids and expected state: recorded + supplement."""
    recorded = [(fid, FIXTURE_STATE_MAP[fid]) for fid in FIXTURE_STATE_MAP]
    supplement = [(f"supplement/{s}/{f}", st) for (s, f, st) in _list_supplement_fixtures()]
    return recorded + supplement


def _load_fixture(fixture_id: str) -> bytes:
    """Load screenshot by fixture id (recorded dir name or 'supplement/state/filename')."""
    if fixture_id.startswith("supplement/"):
        return (FIXTURES / fixture_id).read_bytes()
    return _screenshot_bytes(fixture_id)


# UiState → state group name for cross-validation (which detector should match)
def _state_group(state: UiState) -> str:
    return {
        UiState.WECHAT_MAIN: "wechat_main",
        UiState.DISCOVER_PAGE: "discover_page",
        UiState.MOMENTS_FEED: "moments_feed",
        UiState.CAMERA_BOTTOM_SHEET: "camera_bottom_sheet",
        UiState.ALBUM_PICKER: "album_picker",
        UiState.ALBUM_DROPDOWN: "album_dropdown",
        UiState.INPUT_TEXT: "input_text",
        UiState.DISCARD_DIALOG: "discard_dialog",
    }.get(state, "")


@pytest.mark.parametrize("fixture_id,expected_state", _identify_fixture_ids())
def test_identify_state(fixture_id: str, expected_state: UiState) -> None:
    """Test that _identify_state correctly identifies the UI state from screenshots."""
    screenshot = _load_fixture(fixture_id)
    plan = PlanState(text="test", image_count=3)
    # For INPUT_TEXT fixtures, simulate that we've entered compose through normal flow
    if expected_state == UiState.INPUT_TEXT:
        plan.compose_entered_clean = True
    identified = _identify_state("", screenshot, plan)
    assert identified == expected_state, (
        f"{fixture_id}: expected {expected_state.value}, got {identified.value}"
    )


def test_identify_state_without_plan() -> None:
    """Test that _identify_state works without plan argument (crash recovery scenario)."""
    # This tests the fix for: _identify_state() missing 1 required positional argument: 'plan'
    screenshot = _load_fixture("P2S02_tap_tap_album_option")
    # Should not raise TypeError
    state = _identify_state("", screenshot)
    assert state == UiState.CAMERA_BOTTOM_SHEET


class TestCvFunctions:
    """Test individual CV detection functions (using recorded fixtures)."""

    def test_detect_bottom_sheet_positive(self) -> None:
        from wechat_moments.cv import detect_bottom_sheet

        screenshot = _screenshot_bytes("P2S02_tap_tap_album_option")
        assert detect_bottom_sheet(screenshot), "Should detect bottom sheet in P2S02"

    def test_find_album_option_in_bottom_sheet(self) -> None:
        """Test that find_album_option_in_bottom_sheet returns coords close to profile values."""
        from wechat_moments.calibration import load_profile
        from wechat_moments.cv import find_album_option_in_bottom_sheet

        screenshot = _screenshot_bytes("P2S02_tap_tap_album_option")
        coords = find_album_option_in_bottom_sheet(screenshot)

        assert coords is not None, "Should find album option in bottom sheet"
        x, y = coords

        # Load profile to get expected values
        profile = load_profile("huawei_default")
        profile_x, profile_y = profile.album_option_coords()

        # Detected coords should be within 50 pixels of profile coords
        assert abs(x - profile_x) <= 50, f"X diff too large: detected {x}, profile {profile_x}"
        assert abs(y - profile_y) <= 50, f"Y diff too large: detected {y}, profile {profile_y}"

    def test_find_album_option_returns_none_for_non_bottom_sheet(self) -> None:
        """Test that find_album_option_in_bottom_sheet returns None for non-bottom-sheet screens."""
        from wechat_moments.cv import find_album_option_in_bottom_sheet

        # Test with moments feed screenshot (not a bottom sheet)
        screenshot = _screenshot_bytes("P2S01_tap_tap_camera_button")
        coords = find_album_option_in_bottom_sheet(screenshot)
        assert coords is None, "Should return None for non-bottom-sheet screen"

    def test_find_dropdown_button_in_album_picker(self) -> None:
        """Test that find_dropdown_button_in_album_picker returns coords close to profile values."""
        from wechat_moments.calibration import load_profile
        from wechat_moments.cv import find_dropdown_button_in_album_picker

        screenshot = _screenshot_bytes("P2S03_tap_tap_album_dropdown")
        coords = find_dropdown_button_in_album_picker(screenshot)

        assert coords is not None, "Should find dropdown button in album picker"
        x, y = coords

        # Load profile to get expected values
        profile = load_profile("huawei_default")
        profile_x, profile_y = profile.album_dropdown_coords()

        # Detected coords should be within 50 pixels of profile coords
        assert abs(x - profile_x) <= 50, f"X diff too large: detected {x}, profile {profile_x}"
        assert abs(y - profile_y) <= 50, f"Y diff too large: detected {y}, profile {profile_y}"

    def test_find_dropdown_button_returns_none_for_non_album_picker(self) -> None:
        """Test that find_dropdown_button_in_album_picker returns None for non-album-picker screens."""
        from wechat_moments.cv import find_dropdown_button_in_album_picker

        # Test with bottom sheet screenshot (not an album picker)
        screenshot = _screenshot_bytes("P2S02_tap_tap_album_option")
        coords = find_dropdown_button_in_album_picker(screenshot)
        assert coords is None, "Should return None for non-album-picker screen"

    def test_detect_bottom_sheet_negative(self) -> None:
        from wechat_moments.cv import detect_bottom_sheet

        screenshot = _screenshot_bytes("P2S01_tap_tap_camera_button")
        assert not detect_bottom_sheet(screenshot), "Should not detect bottom sheet in P2S01"

    def test_detect_center_dialog_positive(self) -> None:
        from wechat_moments.cv import detect_center_dialog

        screenshot = _screenshot_bytes("P2S12_tap_tap_discard_button")
        assert detect_center_dialog(screenshot), "Should detect center dialog in P2S12"

    def test_detect_center_dialog_negative(self) -> None:
        from wechat_moments.cv import detect_center_dialog

        screenshot = _screenshot_bytes("P2S11_tap_tap_back_button")
        assert not detect_center_dialog(screenshot), "Should not detect center dialog in P2S11"

    def test_count_green_checkmarks(self) -> None:
        from wechat_moments.cv import count_green_checkmarks

        screenshot = _screenshot_bytes("P2S07_tap_select_image_6__row2_col2_")
        count = count_green_checkmarks(screenshot)
        assert count >= 2, f"Expected at least 2 checkmarks, got {count}"

    def test_detect_active_tab_discover(self) -> None:
        pytest.skip("Tab detection test needs post-action screenshots")

    def test_detect_active_tab_wechat(self) -> None:
        from wechat_moments.cv import detect_active_tab

        screenshot = _screenshot_bytes("P1S01_wait_wechat_main_screen")
        tab = detect_active_tab(screenshot)
        assert tab == "wechat", f"Expected 'wechat' tab, got {tab}"

    def test_has_tab_bar_positive(self) -> None:
        from wechat_moments.cv import has_tab_bar

        screenshot = _screenshot_bytes("P1S01_wait_wechat_main_screen")
        assert has_tab_bar(screenshot), "Should detect tab bar in P1S01"

    def test_is_compose_screen(self) -> None:
        from wechat_moments.cv import has_green_submit_button

        screenshot = _screenshot_bytes("P2S09_tap_tap_text_area")
        assert has_green_submit_button(screenshot), "Should detect green submit button in P2S09"

    @pytest.mark.parametrize("state_dir,filename", _list_other_fixtures())
    def test_other_screens_identified_as_force_restart(self, state_dir: str, filename: str) -> None:
        """Supplement/other/ = 其他页面 (未分类). Must be FORCE_RESTART so no state is misidentified."""
        fixture_id = f"supplement/{state_dir}/{filename}"
        screenshot = _load_fixture(fixture_id)
        plan = PlanState(text="test", image_count=1)
        identified = _identify_state("", screenshot, plan)
        assert identified == UiState.FORCE_RESTART, (
            f"{fixture_id}: other pages must be FORCE_RESTART (got {identified.value})"
        )


class TestCvCrossValidation:
    """Cross-validation: each CV function should only match its target pages (recorded + supplement)."""

    TAB_BAR_GROUPS = ("wechat_main", "discover_page")
    MOMENTS_FEED_GROUPS = ("moments_feed",)
    BOTTOM_SHEET_GROUPS = ("camera_bottom_sheet",)
    ALBUM_PICKER_GROUPS = ("album_picker",)
    ALBUM_DROPDOWN_GROUPS = ("album_dropdown",)
    SUBMIT_BUTTON_GROUPS = ("input_text",)
    CENTER_DIALOG_GROUPS = ("discard_dialog",)

    @staticmethod
    def _all_fixtures_with_group() -> list[tuple[str, str]]:
        """(fixture_id, state_group) for every recorded and supplement fixture."""
        out: list[tuple[str, str]] = []
        for fid, state in _identify_fixture_ids():
            if fid.startswith("supplement/"):
                # supplement/moments_feed/01.png -> group "moments_feed"
                state_group = fid.split("/")[1]
                out.append((fid, state_group))
            else:
                out.append((fid, _state_group(state)))
        return out

    def test_has_tab_bar_cross_validation(self) -> None:
        from wechat_moments.cv import has_tab_bar

        for fixture_id, state_group in self._all_fixtures_with_group():
            screenshot = _load_fixture(fixture_id)
            result = has_tab_bar(screenshot)
            expected = state_group in self.TAB_BAR_GROUPS
            assert result == expected, (
                f"has_tab_bar({fixture_id}): expected {expected}, got {result}"
            )

    def test_is_moments_feed_cross_validation(self) -> None:
        from wechat_moments.cv import is_moments_feed

        for fixture_id, state_group in self._all_fixtures_with_group():
            screenshot = _load_fixture(fixture_id)
            result = is_moments_feed(screenshot)
            expected = state_group in self.MOMENTS_FEED_GROUPS
            assert result == expected, (
                f"is_moments_feed({fixture_id}): expected {expected}, got {result}"
            )

    def test_detect_bottom_sheet_cross_validation(self) -> None:
        from wechat_moments.cv import detect_bottom_sheet

        for fixture_id, state_group in self._all_fixtures_with_group():
            screenshot = _load_fixture(fixture_id)
            result = detect_bottom_sheet(screenshot)
            expected = state_group in self.BOTTOM_SHEET_GROUPS
            assert result == expected, (
                f"detect_bottom_sheet({fixture_id}): expected {expected}, got {result}"
            )

    def test_find_album_option_cross_validation(self) -> None:
        """Test find_album_option_in_bottom_sheet across all fixtures."""
        from wechat_moments.calibration import load_profile
        from wechat_moments.cv import find_album_option_in_bottom_sheet

        profile = load_profile("huawei_default")
        profile_x, profile_y = profile.album_option_coords()

        for fixture_id, state_group in self._all_fixtures_with_group():
            screenshot = _load_fixture(fixture_id)
            coords = find_album_option_in_bottom_sheet(screenshot)

            if state_group in self.BOTTOM_SHEET_GROUPS:
                # Should find coords and they should be close to profile
                assert coords is not None, f"Should find album option in {fixture_id}"
                x, y = coords
                assert abs(x - profile_x) <= 50, (
                    f"X diff too large in {fixture_id}: detected {x}, profile {profile_x}"
                )
                assert abs(y - profile_y) <= 50, (
                    f"Y diff too large in {fixture_id}: detected {y}, profile {profile_y}"
                )
            else:
                # Should return None for non-bottom-sheet screens
                assert coords is None, (
                    f"Should return None for non-bottom-sheet {fixture_id}, got {coords}"
                )

    def test_is_album_picker_cross_validation(self) -> None:
        from wechat_moments.cv import is_album_picker

        for fixture_id, state_group in self._all_fixtures_with_group():
            screenshot = _load_fixture(fixture_id)
            result = is_album_picker(screenshot)
            expected = state_group in self.ALBUM_PICKER_GROUPS
            assert result == expected, (
                f"is_album_picker({fixture_id}): expected {expected}, got {result}"
            )

    def test_is_album_dropdown_cross_validation(self) -> None:
        from wechat_moments.cv import is_album_dropdown

        for fixture_id, state_group in self._all_fixtures_with_group():
            screenshot = _load_fixture(fixture_id)
            result = is_album_dropdown(screenshot)
            expected = state_group in self.ALBUM_DROPDOWN_GROUPS
            assert result == expected, (
                f"is_album_dropdown({fixture_id}): expected {expected}, got {result}"
            )

    def test_has_submit_button_area_cross_validation(self) -> None:
        from wechat_moments.cv import has_submit_button_area

        for fixture_id, state_group in self._all_fixtures_with_group():
            screenshot = _load_fixture(fixture_id)
            result = has_submit_button_area(screenshot)
            expected = state_group in self.SUBMIT_BUTTON_GROUPS
            assert result == expected, (
                f"has_submit_button_area({fixture_id}): expected {expected}, got {result}"
            )

    def test_detect_center_dialog_cross_validation(self) -> None:
        from wechat_moments.cv import detect_center_dialog

        for fixture_id, state_group in self._all_fixtures_with_group():
            screenshot = _load_fixture(fixture_id)
            result = detect_center_dialog(screenshot)
            expected = state_group in self.CENTER_DIALOG_GROUPS
            assert result == expected, (
                f"detect_center_dialog({fixture_id}): expected {expected}, got {result}"
            )
