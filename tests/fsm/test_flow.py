"""FSM flow replay tests using MockADB — no phone required.

Note: These tests use pure CV-based state detection (Activity names are ignored
because WeChat blocks them). The expected states reflect what CV can detect.
"""

from pathlib import Path

import pytest

from wechat_moments.calibration import UIProfile, load_profile
from wechat_moments.poster import PlanState, UiState, _identify_state

FIXTURES = Path(__file__).parent / "fixtures"


def _load_profile() -> UIProfile:
    """Load the default Huawei profile for testing."""
    return load_profile("huawei_default")


def _screenshot_bytes(fixture_dir: str) -> bytes:
    """Load screenshot.png from a fixture directory."""
    path = FIXTURES / fixture_dir / "screenshot.png"
    if not path.exists():
        pytest.skip(f"Fixture screenshot not found: {path}")
    return path.read_bytes()


class TestStateTransitions:
    """Test expected state transitions based on fixtures.

    Note: Activity names are ignored (passed as empty string) because WeChat
    blocks Activity detection. All state identification is CV-based.
    """

    def test_wechat_main_to_moments_feed(self) -> None:
        """After tapping Discover tab and Moments entry, should reach MOMENTS_FEED."""
        plan = PlanState(text="test", image_count=1)

        # P1S01: WeChat main screen
        state1 = _identify_state("", _screenshot_bytes("P1S01_wait_wechat_main_screen"), plan)
        assert state1 == UiState.WECHAT_MAIN

        # P1S03: Screenshot is taken BEFORE tap, shows Discover page (green tab active)
        state2 = _identify_state("", _screenshot_bytes("P1S03_tap_tap_moments_entry"), plan)
        assert state2 == UiState.DISCOVER_PAGE  # Discover tab is active (green)

    def test_moments_feed_to_bottom_sheet(self) -> None:
        """Tapping camera should show bottom sheet."""
        plan = PlanState(text="test", image_count=1)

        # P2S01: Moments feed
        state1 = _identify_state("", _screenshot_bytes("P2S01_tap_tap_camera_button"), plan)
        assert state1 == UiState.MOMENTS_FEED

        # P2S02: Bottom sheet visible
        state2 = _identify_state("", _screenshot_bytes("P2S02_tap_tap_album_option"), plan)
        assert state2 == UiState.CAMERA_BOTTOM_SHEET

    def test_album_picker_flow(self) -> None:
        """Album picker should be detected when in gallery app."""
        plan = PlanState(text="test", image_count=3)

        # P2S03: Album picker (before opening dropdown)
        state1 = _identify_state("", _screenshot_bytes("P2S03_tap_tap_album_dropdown"), plan)
        assert state1 == UiState.ALBUM_PICKER, "P2S03 should be ALBUM_PICKER"

        # P2S04: Album dropdown is open
        state2 = _identify_state("", _screenshot_bytes("P2S04_tap_select_wechatmcp_album"), plan)
        assert state2 == UiState.ALBUM_DROPDOWN, "P2S04 should be ALBUM_DROPDOWN"

        # P2S05-P2S08: In album picker (after selecting album)
        for fixture in [
            "P2S05_tap_select_image_1__row1_col1_",
            "P2S06_tap_select_image_5__row2_col1_",
            "P2S07_tap_select_image_6__row2_col2_",
            "P2S08_tap_tap_done_button",
        ]:
            state = _identify_state("", _screenshot_bytes(fixture), plan)
            assert state == UiState.ALBUM_PICKER, f"{fixture} should be ALBUM_PICKER"

    def test_compose_to_discard_dialog(self) -> None:
        """Pressing back in compose should show discard dialog."""
        # P2S11: Compose screen with text already entered (green button) → SUBMIT
        plan_with_text_entered = PlanState(text="test", image_count=1, text_entered=True)
        state1 = _identify_state(
            "", _screenshot_bytes("P2S11_tap_tap_back_button"), plan_with_text_entered
        )
        assert state1 == UiState.SUBMIT  # Has green submit button

        plan = PlanState(text="test", image_count=1)
        # P2S12: Discard dialog visible
        state2 = _identify_state("", _screenshot_bytes("P2S12_tap_tap_discard_button"), plan)
        assert state2 == UiState.DISCARD_DIALOG

    def test_long_text_compose_flow(self) -> None:
        """Long press camera should enter long text compose."""
        plan = PlanState(text="long text", image_count=0)

        # P3S01: Moments feed (before long press)
        state1 = _identify_state("", _screenshot_bytes("P3S01_long_press_long_press_camera"), plan)
        assert state1 == UiState.MOMENTS_FEED

        # P3S02: Long text compose - CV detects as INPUT_TEXT (same visual as image compose)
        # Note: CV cannot distinguish between image compose and long text compose
        state2 = _identify_state("", _screenshot_bytes("P3S02_tap_tap_text_area"), plan)
        assert state2 == UiState.INPUT_TEXT

    def test_long_text_discard_dialog(self) -> None:
        """Pressing back in long text compose should show discard dialog."""
        # P3S04: Long text compose with text already entered (green button) → SUBMIT
        plan_with_text_entered = PlanState(text="test", image_count=0, text_entered=True)
        state1 = _identify_state(
            "", _screenshot_bytes("P3S04_tap_tap_back_button"), plan_with_text_entered
        )
        assert state1 == UiState.SUBMIT  # Has green submit button

        plan = PlanState(text="test", image_count=0)
        # P3S05: Discard dialog visible
        state2 = _identify_state("", _screenshot_bytes("P3S05_tap_tap_discard_button"), plan)
        assert state2 == UiState.DISCARD_DIALOG


class TestExpectedStateSequence:
    """Test that the expected state sequence matches the fixture order.

    Note: Activity names are ignored. Expected states reflect CV detection results.
    Screenshots are taken BEFORE actions, so states reflect pre-action UI.
    """

    # Expected state sequence for image post flow (Phase 2)
    # Note: P1S03 shows Discover page (green tab active) because screenshot is pre-action
    IMAGE_POST_SEQUENCE = [
        ("P1S01_wait_wechat_main_screen", UiState.WECHAT_MAIN),
        ("P1S02_tap_tap_discover_tab", UiState.WECHAT_MAIN),
        ("P1S03_tap_tap_moments_entry", UiState.DISCOVER_PAGE),  # Pre-action: Discover tab active
        ("P2S01_tap_tap_camera_button", UiState.MOMENTS_FEED),
        ("P2S02_tap_tap_album_option", UiState.CAMERA_BOTTOM_SHEET),
        ("P2S03_tap_tap_album_dropdown", UiState.ALBUM_PICKER),
        ("P2S04_tap_select_wechatmcp_album", UiState.ALBUM_DROPDOWN),
        ("P2S05_tap_select_image_1__row1_col1_", UiState.ALBUM_PICKER),
        ("P2S06_tap_select_image_5__row2_col1_", UiState.ALBUM_PICKER),
        ("P2S07_tap_select_image_6__row2_col2_", UiState.ALBUM_PICKER),
        ("P2S08_tap_tap_done_button", UiState.ALBUM_PICKER),
        ("P2S09_tap_tap_text_area", UiState.INPUT_TEXT),  # Plan has text, not entered yet
        ("P2S10_wait_text_input_complete", UiState.INPUT_TEXT),
        ("P2S11_tap_tap_back_button", UiState.INPUT_TEXT),
        ("P2S12_tap_tap_discard_button", UiState.DISCARD_DIALOG),
    ]

    def test_image_post_state_sequence(self) -> None:
        """Verify all fixtures in image post flow map to expected states."""
        plan = PlanState(text="test", image_count=3)

        for fixture_dir, expected_state in self.IMAGE_POST_SEQUENCE:
            screenshot = _screenshot_bytes(fixture_dir)
            actual_state = _identify_state("", screenshot, plan)
            assert actual_state == expected_state, (
                f"{fixture_dir}: expected {expected_state.value}, got {actual_state.value}"
            )
            # Simulate state changes that would happen during FSM execution
            if fixture_dir == "P2S08_tap_tap_done_button":
                # After tapping done in album picker, we enter compose cleanly
                plan.compose_entered_clean = True

    # Expected state sequence for long text post flow (Phase 3)
    # Note: CV detects green submit button as SUBMIT state
    LONG_TEXT_SEQUENCE = [
        ("P3S01_long_press_long_press_camera", UiState.MOMENTS_FEED),
        ("P3S02_tap_tap_text_area", UiState.INPUT_TEXT),  # Gray button (no text yet)
        ("P3S03_wait_text_input_complete", UiState.INPUT_TEXT),  # Plan has text, not entered yet
        ("P3S04_tap_tap_back_button", UiState.INPUT_TEXT),
        ("P3S05_tap_tap_discard_button", UiState.DISCARD_DIALOG),
    ]

    def test_long_text_state_sequence(self) -> None:
        """Verify all fixtures in long text flow map to expected states."""
        plan = PlanState(text="long text", image_count=0)

        for fixture_dir, expected_state in self.LONG_TEXT_SEQUENCE:
            screenshot = _screenshot_bytes(fixture_dir)
            actual_state = _identify_state("", screenshot, plan)
            assert actual_state == expected_state, (
                f"{fixture_dir}: expected {expected_state.value}, got {actual_state.value}"
            )
