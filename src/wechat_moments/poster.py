"""
UI FSM for posting to WeChat Moments.

Execution loop: OBSERVE → IDENTIFY → SELECT ACTION → EXECUTE → repeat

State detection uses Activity name (from dumpsys) + screenshot CV instead of
UI tree (uiautomator), because WeChat blocks uiautomator with FLAG_SECURE.
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from .adb import ADB
from .calibration import UIProfile
from .config import (
    ALBUM_DROPDOWN_SCROLL_RETRIES,
    ALBUM_DROPDOWN_SCROLL_WAIT_MS,
    FSM_CYCLE_WINDOW,
    FSM_FORCE_RESTART_MAX,
    FSM_MAX_STEPS,
    FSM_STEP_DELAY_SECONDS,
    FSM_TIMEOUT_SECONDS,
    FSM_UNKNOWN_TIMEOUT_SECONDS,
    SCREENSHOT_COOLDOWN_MS,
    SELECT_IMAGES_CHECKMARK_RETRIES,
    SELECT_IMAGES_WAIT_MS,
    WECHAT_PACKAGE,
)

logger = logging.getLogger(__name__)
from .cv import (
    annotate_screenshot_for_debug,
    count_green_checkmarks,
    detect_active_tab,
    detect_bottom_sheet,
    detect_center_dialog,
    find_album_option_in_bottom_sheet,
    find_dropdown_button_in_album_picker,
    find_green_done_button_in_picker,
    find_wechatmcp_in_album_dropdown,
    has_back_arrow,
    has_green_submit_button,
    has_image_thumbnails_in_compose,
    has_submit_button_area,
    has_tab_bar,
    is_album_dropdown,
    is_album_filter_screen,
    is_album_picker,
    is_moments_feed,
)
from .images import ImageFSM, ImageState
from .ime import ImeManager

if TYPE_CHECKING:
    from pathlib import Path


class FsmError(RuntimeError):
    pass


# Callback type for reporting FSM step progress: (step_number, state_name, action_description)
StepCallback = Callable[[int, str, str], None]


class UiState(Enum):
    LAUNCH_WECHAT = "LAUNCH_WECHAT"
    WECHAT_MAIN = "WECHAT_MAIN"
    DISCOVER_PAGE = "DISCOVER_PAGE"  # On Discover tab, need to tap Moments entry
    MOMENTS_FEED = "MOMENTS_FEED"
    CAMERA_BOTTOM_SHEET = "CAMERA_BOTTOM_SHEET"
    ALBUM_PICKER = "ALBUM_PICKER"
    ALBUM_DROPDOWN = "ALBUM_DROPDOWN"  # Album dropdown menu is open
    ALBUM_FILTER = "ALBUM_FILTER"  # Album filter/category sub-screen (tap back to exit)
    MOMENTS_COMPOSE = "MOMENTS_COMPOSE"
    LONG_TEXT_COMPOSE = "LONG_TEXT_COMPOSE"
    DISCARD_DIALOG = "DISCARD_DIALOG"
    INPUT_TEXT = "INPUT_TEXT"
    SUBMIT = "SUBMIT"
    DONE = "DONE"
    ERROR = "ERROR"
    FORCE_RESTART = "FORCE_RESTART"


@dataclass
class PlanState:
    text: str
    image_count: int
    force_restart_count: int = 0  # Counts FORCE_RESTART executions (max FSM_FORCE_RESTART_MAX)
    discard_used: bool = False
    checkmark_retries: int = 0
    text_entered: bool = False
    submitted: bool = False  # True after tapping "发表" button
    album_switched: bool = False  # True after switching to WeChatMCP album
    album_exited_for_refresh: bool = False  # True after exiting album picker to refresh media
    album_entered_from_bottom_sheet: bool = (
        False  # True after entering album from bottom sheet (normal flow)
    )
    compose_entered_clean: bool = (
        False  # True after entering compose via normal flow (not from draft)
    )
    current_state: UiState = UiState.LAUNCH_WECHAT
    error: str | None = None


# Activity short class names for state detection
ACTIVITY_LAUNCHER = "LauncherUI"
ACTIVITY_MOMENTS_FEED = "SnsTimeLineUI"
ACTIVITY_COMPOSE = "SnsUploadUI"
ACTIVITY_LONG_TEXT = "SnsLongTextUI"


def _identify_state(activity: str, screenshot: bytes, plan: PlanState | None = None) -> UiState:
    """
    Identify the current UI state purely from screenshot CV features.

    WeChat blocks Activity name detection, so we rely entirely on visual features.

    Detection priority (most specific first):
    0. Already submitted: return DONE
    1. Overlays: dialog, bottom sheet (can appear on any page)
    2. Compose screen: green or gray "发表" button area
    3. Album dropdown: bright right side (album list) + dark left side
    4. Album picker: dark header + image grid
    5. Moments feed: back arrow + camera icon + no tab bar
    6. WeChat main: tab bar visible
    7. Unknown: force restart

    Args:
        activity: Ignored (WeChat blocks this)
        screenshot: PNG bytes of current screen
        plan: Current plan state for context (optional, uses defaults if None)

    Returns:
        The identified UiState
    """
    # Use default plan if not provided (e.g., crash recovery)
    if plan is None:
        plan = PlanState(text="", image_count=0)

    # --- Priority 0: Already submitted ---
    if plan.submitted:
        return UiState.DONE

    # --- Priority 1: Overlay detection (can appear on any page) ---

    # Check for center dialog (discard confirmation)
    if detect_center_dialog(screenshot):
        return UiState.DISCARD_DIALOG

    # Check for bottom sheet (camera options)
    if detect_bottom_sheet(screenshot):
        return UiState.CAMERA_BOTTOM_SHEET

    # --- Priority 2: Compose screen (green or gray "发表" button) ---
    if has_submit_button_area(screenshot):
        # Check for dirty state (draft content from previous session)
        # Only applies when we have images to post and haven't gone through album picker yet
        # For text-only posts (image_count=0), entering compose directly is expected
        if (
            plan.image_count > 0
            and not plan.compose_entered_clean
            and not plan.text_entered
            and not plan.album_switched
        ):
            return UiState.MOMENTS_COMPOSE

        # Only treat as INPUT_TEXT when we're clearly on compose (have images or green button).
        # Avoids misidentifying e.g. moments feed as compose and losing text after re-entry.
        if plan.text and not plan.text_entered:
            if has_image_thumbnails_in_compose(screenshot) or has_green_submit_button(screenshot):
                return UiState.INPUT_TEXT
        # Check if green submit button is visible (ready to submit)
        if has_green_submit_button(screenshot):
            return UiState.SUBMIT
        # Check for stale content (image thumbnails already present but no green button)
        # This indicates leftover content from a previous unfinished post
        # Only consider it stale if we haven't gone through album picker yet
        if has_image_thumbnails_in_compose(screenshot) and not plan.album_switched:
            return UiState.MOMENTS_COMPOSE
        # Gray button - need to input text
        return UiState.INPUT_TEXT

    # --- Priority 3: Album dropdown (before album picker) ---
    if is_album_dropdown(screenshot):
        return UiState.ALBUM_DROPDOWN

    # --- Priority 4: Album picker (dark header + image grid) ---
    if is_album_picker(screenshot):
        return UiState.ALBUM_PICKER

    # --- Priority 4b: Album filter/category sub-screen (dark header, no dark bottom) ---
    if is_album_filter_screen(screenshot):
        return UiState.ALBUM_FILTER

    # --- Priority 5: Moments feed (back arrow + camera icon + no tab bar) ---
    if is_moments_feed(screenshot):
        return UiState.MOMENTS_FEED

    # --- Priority 6: WeChat main (tab bar visible) ---
    if has_tab_bar(screenshot):
        active_tab = detect_active_tab(screenshot)
        if active_tab == "discover":
            return UiState.DISCOVER_PAGE
        if active_tab == "contacts":
            # Contacts tab visible: may be main list or sub-page (e.g. other user's moments).
            # Treat as FORCE_RESTART so we don't tap discover/camera on wrong page.
            return UiState.FORCE_RESTART
        return UiState.WECHAT_MAIN

    # --- Unknown state ---
    return UiState.FORCE_RESTART


class UiFsm:
    def __init__(
        self,
        adb: ADB,
        profile: UIProfile,
        plan: PlanState,
        image_fsm: ImageFSM,
        debug_dir: Path | None = None,
        step_callback: StepCallback | None = None,
    ):
        self._adb = adb
        self._profile = profile
        self._plan = plan
        self._image_fsm = image_fsm
        self._ime = ImeManager(adb)
        self._debug_dir = debug_dir
        self._step_callback = step_callback

    def _report_step(self, step: int, state: str, action: str) -> None:
        """Report step progress to stderr and optional callback."""
        print(f"[FSM step {step}] state={state} | {action}", flush=True, file=sys.stderr)
        if self._step_callback:
            try:
                self._step_callback(step, state, action)
            except Exception:
                pass  # Don't let callback errors break FSM

    def run(self) -> None:
        """Main FSM execution loop."""
        start_time = time.monotonic()
        unknown_since: float | None = None
        previous_state: UiState | None = None
        state_history: list[UiState] = []

        for step in range(FSM_MAX_STEPS):
            elapsed = time.monotonic() - start_time
            if elapsed > FSM_TIMEOUT_SECONDS:
                raise FsmError(f"FSM timed out after {elapsed:.0f}s")

            for _screenshot_attempt in range(3):
                try:
                    screenshot = self._adb.screenshot()
                    time.sleep(SCREENSHOT_COOLDOWN_MS / 1000.0)
                    activity = self._adb.get_current_activity()
                    state = _identify_state(activity, screenshot, self._plan)
                    break
                except RuntimeError as e:
                    if "incomplete PNG" in str(e) or "Invalid or incomplete" in str(e):
                        if not self._adb.is_device_connected():
                            raise RuntimeError(
                                "No device connected. Connect your phone via USB and run 'adb devices' to confirm it is listed."
                            ) from e
                        if _screenshot_attempt < 2:
                            time.sleep(1.0)
                            continue
                    raise

            # If CV says we're in a WeChat screen but app is not in foreground, launch WeChat first
            if (
                state
                not in (
                    UiState.LAUNCH_WECHAT,
                    UiState.DONE,
                    UiState.ERROR,
                    UiState.FORCE_RESTART,
                )
                and self._adb.get_foreground_package() != WECHAT_PACKAGE
            ):
                state = UiState.LAUNCH_WECHAT

            # After tapping 朋友圈 we may catch a transition; wait and re-identify before FORCE_RESTART
            if (
                state == UiState.FORCE_RESTART
                and previous_state == UiState.DISCOVER_PAGE
                and self._plan.force_restart_count == 0
            ):
                self._adb.wait(2000)
                for _retry in range(3):
                    try:
                        screenshot = self._adb.screenshot()
                        time.sleep(SCREENSHOT_COOLDOWN_MS / 1000.0)
                        state = _identify_state(
                            self._adb.get_current_activity(), screenshot, self._plan
                        )
                        break
                    except RuntimeError as e:
                        if "incomplete PNG" in str(e) or "Invalid or incomplete" in str(e):
                            if not self._adb.is_device_connected():
                                raise RuntimeError(
                                    "No device connected. Connect your phone via USB and run 'adb devices' to confirm it is listed."
                                ) from e
                            if _retry < 2:
                                time.sleep(1.0)
                                continue
                        raise
                if (
                    state
                    not in (
                        UiState.LAUNCH_WECHAT,
                        UiState.DONE,
                        UiState.ERROR,
                        UiState.FORCE_RESTART,
                    )
                    and self._adb.get_foreground_package() != WECHAT_PACKAGE
                ):
                    state = UiState.LAUNCH_WECHAT

            self._plan.current_state = state

            # Cycle detection: if last 2k states repeat (first k == second k), abort
            state_history.append(state)
            if len(state_history) >= 2 * FSM_CYCLE_WINDOW:
                window = state_history[-2 * FSM_CYCLE_WINDOW :]
                if window[:FSM_CYCLE_WINDOW] == window[FSM_CYCLE_WINDOW:]:
                    cycle_str = " → ".join(s.value for s in window[:FSM_CYCLE_WINDOW])
                    raise FsmError(f"FSM cycle detected: {cycle_str}")
                # Keep only tail to prevent unbounded memory growth
                state_history = state_history[-2 * FSM_CYCLE_WINDOW :]

            if self._debug_dir is not None:
                self._debug_dir.mkdir(parents=True, exist_ok=True)
                prefix = f"step_{step + 1:03d}_{state.value}"
                (self._debug_dir / f"{prefix}_raw.png").write_bytes(screenshot)
                annotated = annotate_screenshot_for_debug(
                    screenshot, None, f"step {step + 1} {state.value}"
                )
                (self._debug_dir / f"{prefix}_annotated.png").write_bytes(annotated)

            if state == UiState.FORCE_RESTART:
                if unknown_since is None:
                    unknown_since = time.monotonic()
                elif time.monotonic() - unknown_since > FSM_UNKNOWN_TIMEOUT_SECONDS:
                    raise FsmError("Could not identify WeChat state for 60s")
            else:
                unknown_since = None

            if state == UiState.DONE:
                self._report_step(step + 1, state.value, "完成")
                return

            if state == UiState.ERROR:
                raise FsmError(self._plan.error or "FSM reached ERROR state")

            # Prefer tapping back over full app restart when back button is visible (unknown page)
            if state == UiState.FORCE_RESTART and has_back_arrow(screenshot):
                for _ in range(2):
                    self._adb.press_back()
                    self._adb.wait(600)
                action = "按后退键x2"
                self._report_step(step + 1, state.value, action)
                previous_state = state
                time.sleep(FSM_STEP_DELAY_SECONDS)
                continue

            action = self._execute(state, screenshot)
            self._report_step(step + 1, state.value, action)
            previous_state = state
            time.sleep(FSM_STEP_DELAY_SECONDS)

        raise FsmError(f"FSM exceeded max steps ({FSM_MAX_STEPS})")

    def run_and_collect_states(self) -> list[str]:
        """Run FSM and return list of visited state names (for testing)."""
        visited: list[str] = []
        start_time = time.monotonic()

        for _ in range(FSM_MAX_STEPS):
            if time.monotonic() - start_time > FSM_TIMEOUT_SECONDS:
                break
            screenshot = self._adb.screenshot()
            time.sleep(SCREENSHOT_COOLDOWN_MS / 1000.0)
            activity = self._adb.get_current_activity()
            state = _identify_state(activity, screenshot, self._plan)
            self._plan.current_state = state
            visited.append(state.value)
            if state in (UiState.DONE, UiState.ERROR):
                break
            self._execute(state, screenshot)
            time.sleep(FSM_STEP_DELAY_SECONDS)

        return visited

    def _execute(self, state: UiState, screenshot: bytes) -> str:
        match state:
            case UiState.LAUNCH_WECHAT:
                self._adb.start_app(WECHAT_PACKAGE)
                self._adb.wait(2000)
                return "启动微信"

            case UiState.WECHAT_MAIN:
                x, y = self._profile.tab_coords(2)
                self._adb.tap(x, y)
                self._adb.wait(1000)
                return "点击发现 tab"

            case UiState.DISCOVER_PAGE:
                x, y = self._profile.moments_entry_coords()
                self._adb.tap(x, y)
                self._adb.wait(2500)  # Allow moments feed to fully load before next screenshot
                return "点击朋友圈"

            case UiState.MOMENTS_FEED:
                cam_x, cam_y = self._profile.camera_coords()
                if self._plan.image_count > 0:
                    self._adb.tap(cam_x, cam_y)
                    action = "点击相机"
                else:
                    self._adb.long_press(cam_x, cam_y)
                    action = "长按相机"
                self._adb.wait(1200)
                return action

            case UiState.CAMERA_BOTTOM_SHEET:
                # Try layout detection first to find "从相册选择" button
                screenshot = self._adb.screenshot()
                coords = find_album_option_in_bottom_sheet(screenshot)
                profile_x, profile_y = self._profile.album_option_coords()

                if coords:
                    x, y = coords
                    # Sanity check: detected coords should be close to profile coords
                    # If difference > 100px, fall back to profile (detection may be wrong)
                    if abs(x - profile_x) > 100 or abs(y - profile_y) > 100:
                        x, y = profile_x, profile_y
                else:
                    # Fallback to profile coordinates if detection failed
                    x, y = profile_x, profile_y

                self._adb.tap(x, y)
                self._adb.wait(1000)
                # Mark that we entered album through normal flow (no need to exit for refresh)
                self._plan.album_entered_from_bottom_sheet = True
                return "点击从相册选择"

            case UiState.ALBUM_PICKER:
                # If FSM started with album already open (not entered from bottom sheet),
                # exit first to let the system refresh media (newly pushed images won't show otherwise)
                if (
                    not self._plan.album_switched
                    and not self._plan.album_exited_for_refresh
                    and not self._plan.album_entered_from_bottom_sheet
                ):
                    self._plan.album_exited_for_refresh = True
                    self._adb.press_back()
                    self._adb.wait(800)
                    return "退出相册刷新媒体"

                if not self._plan.album_switched:
                    # Try layout detection first to find dropdown button
                    screenshot = self._adb.screenshot()
                    coords = find_dropdown_button_in_album_picker(screenshot)
                    profile_x, profile_y = self._profile.album_dropdown_coords()

                    if coords:
                        x, y = coords
                        # Sanity check: detected coords should be close to profile coords
                        if abs(x - profile_x) > 100 or abs(y - profile_y) > 100:
                            x, y = profile_x, profile_y
                    else:
                        x, y = profile_x, profile_y

                    self._adb.tap(x, y)
                    self._adb.wait(800)
                    return "点击相册下拉"

                if self._image_fsm.state != ImageState.READY:
                    if self._image_fsm.state == ImageState.ERROR:
                        raise FsmError(f"Image push failed: {self._image_fsm.error}")
                    self._adb.wait(SELECT_IMAGES_WAIT_MS)
                    return "等待图片"

                for i in range(self._plan.image_count):
                    x, y = self._profile.album_cell_coords(i)
                    self._adb.tap(x, y)
                    self._adb.wait(200)

                screenshot2 = self._adb.screenshot()
                checkmarks = count_green_checkmarks(screenshot2)
                if checkmarks != self._plan.image_count:
                    self._plan.checkmark_retries += 1
                    if self._plan.checkmark_retries > SELECT_IMAGES_CHECKMARK_RETRIES:
                        raise FsmError(
                            f"ALBUM_PICKER: expected {self._plan.image_count} checkmarks, "
                            f"got {checkmarks} after {SELECT_IMAGES_CHECKMARK_RETRIES} retries"
                        )
                    return "等待勾选"

                screenshot_for_done = self._adb.screenshot()
                coords_done = find_green_done_button_in_picker(screenshot_for_done)
                x, y = coords_done if coords_done else self._profile.album_done_coords()
                tap_source = "green" if coords_done else "profile"
                logger.info("ALBUM_PICKER: tap 完成 at (%s, %s) source=%s", x, y, tap_source)
                if self._debug_dir is not None:
                    self._debug_dir.mkdir(parents=True, exist_ok=True)
                    path = self._debug_dir / "album_picker_before_done.png"
                    annotated = annotate_screenshot_for_debug(
                        screenshot_for_done, (x, y), tap_source
                    )
                    path.write_bytes(annotated)
                    logger.info("ALBUM_PICKER: saved debug screenshot to %s", path)
                self._adb.tap(x, y)
                self._adb.wait(1000)
                # Mark that we've entered compose through normal flow (not from draft)
                self._plan.compose_entered_clean = True
                return f"点击完成 ({x},{y}) source={tap_source}"

            case UiState.ALBUM_FILTER:
                # 相册筛选/分类子页；按返回回到上一级。部分设备返回会直接退出相册流程到朋友圈，下一轮会重新进入并依赖 album_switched 直接选图
                self._adb.press_back()
                self._adb.wait(800)
                return "按返回"

            case UiState.ALBUM_DROPDOWN:
                # Find WeChatMCP by OCR and tap; if not visible, scroll list and retry
                w, h = self._profile.screen_width, self._profile.screen_height
                list_center_x = int(w * 0.58)
                swipe_from_y = int(h * 0.70)
                swipe_to_y = int(h * 0.30)

                for attempt in range(ALBUM_DROPDOWN_SCROLL_RETRIES):
                    screenshot = self._adb.screenshot()
                    coords = find_wechatmcp_in_album_dropdown(screenshot)
                    if coords is None:
                        coords = (
                            self._profile.album_wechatmcp_coords()
                        )  # Fallback when OCR unavailable
                    if coords:
                        x, y = coords
                        self._adb.tap(x, y)
                        self._adb.wait(700)
                        screenshot_after = self._adb.screenshot()
                        state_after = _identify_state("", screenshot_after, self._plan)
                        if state_after != UiState.ALBUM_DROPDOWN:
                            self._plan.album_switched = True
                            self._adb.wait(300)
                            return "点击 WeChatMCP" if attempt == 0 else "滚动后点击 WeChatMCP"

                    if attempt < ALBUM_DROPDOWN_SCROLL_RETRIES - 1:
                        self._adb.swipe(list_center_x, swipe_from_y, list_center_x, swipe_to_y, 300)
                        self._adb.wait(ALBUM_DROPDOWN_SCROLL_WAIT_MS)

                raise FsmError(
                    "ALBUM_DROPDOWN: WeChatMCP album not found after "
                    f"{ALBUM_DROPDOWN_SCROLL_RETRIES} scroll attempts (OCR or scroll)"
                )

            case UiState.MOMENTS_COMPOSE:
                if self._plan.discard_used:
                    raise FsmError("MOMENTS_COMPOSE: stale content detected again after discard")
                self._adb.press_back()
                self._adb.wait(600)
                return "按返回(触发丢弃弹窗)"

            case UiState.DISCARD_DIALOG:
                if self._plan.discard_used:
                    raise FsmError("DISCARD_DIALOG appeared twice; aborting to prevent loop")
                self._plan.discard_used = True
                x, y = self._profile.discard_abandon_coords()
                self._adb.tap(x, y)
                self._adb.wait(600)
                return "点击不保留"

            case UiState.INPUT_TEXT:
                if self._plan.text:
                    x, y = self._profile.compose_text_coords()
                    self._adb.tap(x, y)
                    self._adb.wait(300)
                    self._ime.input_with_ime_switch(self._plan.text)
                    self._adb.wait(500)
                self._plan.text_entered = True
                return "点击输入框并输入文案" if self._plan.text else "点击输入框"

            case UiState.LONG_TEXT_COMPOSE:
                if not self._plan.text_entered:
                    x, y = self._profile.compose_text_coords()
                    self._adb.tap(x, y)
                    self._adb.wait(300)
                    if self._plan.text:
                        self._ime.input_with_ime_switch(self._plan.text)
                        self._adb.wait(500)
                    self._plan.text_entered = True
                    return "点击输入框并输入文案"
                else:
                    x, y = self._profile.long_text_submit_coords()
                    self._adb.tap(x, y)
                    self._adb.wait(2000)
                    return "点击发表"

            case UiState.SUBMIT:
                x, y = self._profile.compose_submit_coords()
                self._adb.tap(x, y)
                self._adb.wait(2000)
                self._plan.submitted = True
                return "点击发表"

            case UiState.FORCE_RESTART:
                # Check restart limit before executing
                if self._plan.force_restart_count >= FSM_FORCE_RESTART_MAX:
                    raise FsmError(f"FORCE_RESTART exceeded max attempts ({FSM_FORCE_RESTART_MAX})")
                self._plan.force_restart_count += 1

                # First time: bring WeChat to foreground (avoid 3x back which can exit app)
                if self._plan.force_restart_count == 1:
                    self._adb.start_app(WECHAT_PACKAGE)
                    self._adb.wait(2000)
                    return "唤起微信"
                else:
                    self._adb.force_stop(WECHAT_PACKAGE)
                    self._adb.wait(500)
                    self._adb.start_app(WECHAT_PACKAGE)
                    self._adb.wait(2000)
                    return "重启微信"

            case _:
                self._adb.wait(500)
                return "等待"
