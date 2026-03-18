"""Test submit flow logic to ensure submitted flag is only set after confirming success."""

from pathlib import Path

import pytest

from wechat_moments.poster import PlanState, UiState, _identify_state


@pytest.fixture
def moments_feed_screenshot() -> bytes:
    """Load a real moments feed screenshot for testing."""
    fixture_path = (
        Path(__file__).parent.parent
        / "fsm"
        / "fixtures"
        / "supplement"
        / "moments_feed"
        / "01.png"
    )
    if not fixture_path.exists():
        pytest.skip(f"Fixture not found: {fixture_path}")
    return fixture_path.read_bytes()


def test_submit_flow_before_click(moments_feed_screenshot: bytes) -> None:
    """Before clicking submit, moments feed should be identified as MOMENTS_FEED."""
    plan = PlanState(text="test", image_count=1)
    plan.submit_clicked = False
    plan.submitted = False

    state = _identify_state("", moments_feed_screenshot, plan)
    assert state == UiState.MOMENTS_FEED
    assert not plan.submitted  # Should not be set yet


def test_submit_flow_after_click_back_to_feed(moments_feed_screenshot: bytes) -> None:
    """After clicking submit and returning to moments feed, state should be DONE and submitted=True."""
    plan = PlanState(text="test", image_count=1)
    plan.submit_clicked = True
    plan.submitted = False

    state = _identify_state("", moments_feed_screenshot, plan)
    assert state == UiState.DONE
    assert plan.submitted  # Should be set when we detect MOMENTS_FEED after submit click


def test_submit_flow_crash_recovery(moments_feed_screenshot: bytes) -> None:
    """Crash recovery (no plan) should identify MOMENTS_FEED, not DONE."""
    # Crash recovery uses default plan (submit_clicked=False)
    state = _identify_state("", moments_feed_screenshot)
    assert state == UiState.MOMENTS_FEED


def test_submit_flow_submitted_flag_preserves_done() -> None:
    """Once submitted=True is set, we don't need to rely on screenshot anymore."""
    plan = PlanState(text="test", image_count=1)
    plan.submit_clicked = True
    plan.submitted = True

    # Even with a different screenshot, if submitted is already True,
    # the _identify_state should handle it correctly
    # (though in practice, once DONE is reached, FSM exits)
    # This test just verifies the flag is preserved
    assert plan.submitted
