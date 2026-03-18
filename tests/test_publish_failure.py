"""Test for publish failure bug where step 18 shows moments feed but post wasn't published.

This test reproduces a bug where:
1. User taps "发表" (submit) button at step 14-17
2. At step 18, CV detects moments feed (is_moments_feed returns True)
3. FSM marks post as DONE because submit_clicked=True and is_moments_feed=True
4. BUT the post wasn't actually published (submission failed)

Root cause: poster.py lines 201-206 assume that if submit_clicked=True and
is_moments_feed(screenshot)=True, then the post was successfully published.
This is a flawed assumption because:
- Submit could have failed (network error, validation error, etc.)
- CV could misidentify another screen as moments feed
- User could have manually navigated back to moments feed without completing submit
"""

from pathlib import Path

import pytest

from wechat_moments.cv import (
    detect_bottom_sheet,
    detect_center_dialog,
    has_back_arrow,
    has_camera_icon_top_right,
    has_submit_button_area,
    has_tab_bar,
    is_album_dropdown,
    is_album_picker,
    is_moments_feed,
)
from wechat_moments.poster import PlanState, UiState, _identify_state

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "screens"


def load_screenshot(filename: str) -> bytes:
    """Load screenshot fixture from tests/fixtures/screens/."""
    path = FIXTURES_DIR / filename
    if not path.exists():
        pytest.skip(f"Fixture not found: {path}")
    return path.read_bytes()


class TestPublishFailureBug:
    """Test suite for the publish failure detection bug."""

    def test_step_014_screen_detection(self):
        """Step 14: Verify what screen we're on before submit."""
        screenshot = load_screenshot("failed_publish_step_014.png")

        # Check basic CV detections
        assert not has_tab_bar(screenshot), "Should not have tab bar"
        assert not detect_bottom_sheet(screenshot), "Should not have bottom sheet"
        assert not detect_center_dialog(screenshot), "Should not have center dialog"

        # Identify state
        state = _identify_state("", screenshot, PlanState(text="test", image_count=1))
        print(f"Step 14 state: {state}")

    def test_step_015_screen_detection(self):
        """Step 15: Check screen state."""
        screenshot = load_screenshot("failed_publish_step_015.png")

        # Check basic CV detections
        has_back = has_back_arrow(screenshot)
        has_camera = has_camera_icon_top_right(screenshot)
        has_tab = has_tab_bar(screenshot)

        print(f"Step 15 - back_arrow: {has_back}, camera: {has_camera}, tab_bar: {has_tab}")

        # Identify state
        state = _identify_state("", screenshot, PlanState(text="test", image_count=1))
        print(f"Step 15 state: {state}")

    def test_step_016_screen_detection(self):
        """Step 16: Check screen state."""
        screenshot = load_screenshot("failed_publish_step_016.png")

        # Check basic CV detections
        has_submit = has_submit_button_area(screenshot)
        is_album = is_album_picker(screenshot)

        print(f"Step 16 - submit_button: {has_submit}, album_picker: {is_album}")

        # Identify state
        state = _identify_state("", screenshot, PlanState(text="test", image_count=1))
        print(f"Step 16 state: {state}")

    def test_step_017_screen_detection(self):
        """Step 17: Check screen state before the problematic step."""
        screenshot = load_screenshot("failed_publish_step_017.png")

        # Check if this is the submit screen
        has_submit = has_submit_button_area(screenshot)

        # Identify state with submit_clicked=False (before submit)
        plan_before = PlanState(text="test", image_count=1, submit_clicked=False)
        state_before = _identify_state("", screenshot, plan_before)

        print(f"Step 17 - submit_button: {has_submit}")
        print(f"Step 17 state (before submit): {state_before}")

    def test_step_018_bug_verification(self):
        """
        Step 18: THE BUG - CV says moments feed but post wasn't published.

        This is the critical test that demonstrates the bug:
        1. After clicking submit (submit_clicked=True)
        2. CV detects moments feed (is_moments_feed returns True)
        3. FSM incorrectly concludes post was published (DONE state)
        4. But actually the post failed to publish
        """
        screenshot = load_screenshot("failed_publish_step_018.png")

        # Check CV detections
        is_feed = is_moments_feed(screenshot)
        has_back = has_back_arrow(screenshot)
        has_camera = has_camera_icon_top_right(screenshot)
        has_tab = has_tab_bar(screenshot)
        has_submit = has_submit_button_area(screenshot)
        is_album = is_album_picker(screenshot)
        is_dropdown = is_album_dropdown(screenshot)

        print(f"\n=== Step 18 CV Detection Results ===")
        print(f"is_moments_feed: {is_feed}")
        print(f"has_back_arrow: {has_back}")
        print(f"has_camera_icon: {has_camera}")
        print(f"has_tab_bar: {has_tab}")
        print(f"has_submit_button: {has_submit}")
        print(f"is_album_picker: {is_album}")
        print(f"is_album_dropdown: {is_dropdown}")

        # Identify state with submit_clicked=True (after submit)
        plan_after_submit = PlanState(
            text="test",
            image_count=1,
            submit_clicked=True,  # This is the key flag
        )
        state_after_submit = _identify_state("", screenshot, plan_after_submit)

        print(f"\n=== State Detection ===")
        print(f"State (with submit_clicked=True): {state_after_submit}")

        # THE BUG: If is_moments_feed=True and submit_clicked=True,
        # poster.py lines 201-206 will return UiState.DONE
        # This assumes the post was successfully published, which may be wrong!

        if is_feed and state_after_submit == UiState.DONE:
            print("\n⚠️  BUG DETECTED!")
            print("CV says this is moments feed AND submit was clicked,")
            print("so FSM marks as DONE (post published).")
            print("But according to the issue, the post was NOT actually published!")
            print("\nPossible causes:")
            print("1. is_moments_feed() incorrectly identifies this screen")
            print("2. Submit failed but we returned to feed anyway")
            print("3. Need additional verification that post was actually created")

        # Assert the bug exists: if CV says moments feed after submit, FSM says DONE
        if is_feed:
            assert state_after_submit == UiState.DONE, (
                "Expected DONE state when is_moments_feed=True and submit_clicked=True "
                "(this demonstrates the bug)"
            )

    def test_false_positive_moments_feed_detection(self):
        """
        Test if step 18 is a false positive in moments feed detection.

        The screen might actually be something else (album picker, compose, etc.)
        but CV incorrectly identifies it as moments feed.
        """
        screenshot = load_screenshot("failed_publish_step_018.png")

        # Run all detection functions to see which ones return True
        detections = {
            "has_back_arrow": has_back_arrow(screenshot),
            "has_camera_icon_top_right": has_camera_icon_top_right(screenshot),
            "has_tab_bar": has_tab_bar(screenshot),
            "detect_bottom_sheet": detect_bottom_sheet(screenshot),
            "detect_center_dialog": detect_center_dialog(screenshot),
            "is_album_picker": is_album_picker(screenshot),
            "is_album_dropdown": is_album_dropdown(screenshot),
            "has_submit_button_area": has_submit_button_area(screenshot),
            "is_moments_feed": is_moments_feed(screenshot),
        }

        print("\n=== All CV Detections for Step 18 ===")
        for name, result in detections.items():
            print(f"{name}: {result}")

        # Analyze: What screen is this REALLY?
        if detections["is_moments_feed"]:
            if detections["has_submit_button_area"]:
                print("\n⚠️  Conflicting signals: both moments_feed AND submit_button detected!")
                print("This might be the root cause - CV is confused.")
            elif not detections["has_back_arrow"]:
                print("\n⚠️  Moments feed without back arrow? Suspicious.")
            elif not detections["has_camera_icon_top_right"]:
                print("\n⚠️  Moments feed without camera icon? Could be scrolled or wrong detection.")

    def test_sequence_analysis(self):
        """Analyze the full sequence from step 14-18 to understand the flow."""
        steps = [
            ("step_014", "failed_publish_step_014.png"),
            ("step_015", "failed_publish_step_015.png"),
            ("step_016", "failed_publish_step_016.png"),
            ("step_017", "failed_publish_step_017.png"),
            ("step_018", "failed_publish_step_018.png"),
        ]

        print("\n=== Full Sequence Analysis ===")

        for step_name, filename in steps:
            try:
                screenshot = load_screenshot(filename)

                # Create appropriate plan state for each step
                if step_name in ["step_014", "step_015", "step_016"]:
                    plan = PlanState(text="test", image_count=1, submit_clicked=False)
                else:
                    # After step 017, assume submit was clicked
                    plan = PlanState(text="test", image_count=1, submit_clicked=True)

                state = _identify_state("", screenshot, plan)
                is_feed = is_moments_feed(screenshot)
                has_submit = has_submit_button_area(screenshot)

                print(f"\n{step_name}:")
                print(f"  State: {state}")
                print(f"  is_moments_feed: {is_feed}")
                print(f"  has_submit_button: {has_submit}")

            except Exception as e:
                print(f"\n{step_name}: Error - {e}")


class TestPublishSuccessVerification:
    """
    Test ideas for verifying publish success (beyond just detecting moments feed).

    These tests explore potential solutions to the bug.
    """

    def test_should_verify_post_in_feed(self):
        """
        Proposed fix: Don't just check if we're on moments feed.
        Instead, verify that a NEW post appears at the top of the feed.

        This could involve:
        1. Taking screenshot of feed before posting
        2. After submit + feed detection, take another screenshot
        3. Compare to verify a new post card appeared
        4. Or use OCR to check for our post text at top of feed
        """
        pytest.skip("This is a proposed fix, not implemented yet")

    def test_should_wait_and_recheck(self):
        """
        Proposed fix: After detecting moments feed post-submit,
        wait a few seconds and check again to ensure we're still on feed
        (not just a brief transition screen).
        """
        pytest.skip("This is a proposed fix, not implemented yet")

    def test_should_check_submit_button_disappearance(self):
        """
        Proposed fix: Verify that the submit button is no longer visible.
        If we can still see the submit button, we're probably still on compose screen.
        """
        pytest.skip("This is a proposed fix, not implemented yet")
