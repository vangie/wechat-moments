"""
submit_post execution: lock, FSM run, archive, history logging.
"""

import json
import time
from pathlib import Path

from .adb import ADB
from .calibration import load_profile
from .config import DATA_DIR, IMAGE_PUSH_HEAD_START_SECONDS, LOCK_FILE, STAGING_DIR
from .history import (
    log_lock_rejected,
    log_possibly_submitted,
    log_submit_failure,
    log_submit_start,
    log_submit_success,
)
from .images import ImageFSM
from .poster import FsmError, PlanState, StepCallback, UiFsm, UiState, _identify_state
from .preview import archive_post, get_post_text, get_staged_images, update_meta_status


class LockError(RuntimeError):
    pass


def _read_active_lock() -> str | None:
    if not LOCK_FILE.exists():
        return None
    try:
        return json.loads(LOCK_FILE.read_text(encoding="utf-8")).get("post_id")
    except Exception:
        return None


def _acquire_lock(post_id: str) -> bool:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        active = _read_active_lock()
        if active:
            return False
    LOCK_FILE.write_text(json.dumps({"post_id": post_id}), encoding="utf-8")
    return True


def _release_lock() -> None:
    LOCK_FILE.unlink(missing_ok=True)


def _get_meta(post_id: str) -> dict:
    meta_path = STAGING_DIR / post_id / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"No staging directory for post_id={post_id!r}")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def execute_submit(
    post_id: str,
    debug_dir: Path | None = None,
    step_callback: StepCallback | None = None,
) -> dict:
    """
    Execute the full post submission flow with locking and idempotency.
    Returns a result dict with 'status' key.
    When debug_dir is set, debug screenshots are saved under that path.
    When step_callback is set, it's called on each FSM step with (step, state, action).
    """
    # --- Idempotency: already submitted? ---
    try:
        meta = _get_meta(post_id)
    except FileNotFoundError:
        # Check archive
        archive_meta = Path.home() / ".local/share/wechat-moments/archive" / post_id / "meta.json"
        if archive_meta.exists():
            data = json.loads(archive_meta.read_text(encoding="utf-8"))
            if data.get("status") == "submitted":
                return {
                    "status": "success",
                    "post_id": post_id,
                    "archive_path": str(archive_meta.parent),
                }
        return {
            "status": "failed",
            "post_id": post_id,
            "error": f"post_id {post_id!r} not found in staging or archive",
        }

    status = meta.get("status", "prepared")

    if status == "submitted":
        return {"status": "success", "post_id": post_id}

    if status == "submitting":
        # Previous crash: check current WeChat state
        return _handle_crash_recovery(post_id)

    # --- Global mutex ---
    if not _acquire_lock(post_id):
        active = _read_active_lock()
        log_lock_rejected(post_id, active or "unknown")
        return {
            "status": "rejected",
            "error": "another submit is in progress",
            "active_post_id": active,
        }

    try:
        start_ms = int(time.monotonic() * 1000)
        adb = ADB.auto_connect()
        adb.wake_screen()
        serial = adb.get_serial()
        profile = load_profile(serial)
        staged_images = get_staged_images(post_id)
        text = get_post_text(post_id)
        image_fsm = ImageFSM(adb, staged_images)
        plan = PlanState(text=text, image_count=len(staged_images))
        fsm = UiFsm(
            adb=adb,
            profile=profile,
            plan=plan,
            image_fsm=image_fsm,
            debug_dir=debug_dir,
            step_callback=step_callback,
        )

        try:
            update_meta_status(post_id, "submitting")
            log_submit_start(post_id)

            # Start image push concurrently
            image_fsm.start()
            # Let push get a head start so first screencap is not parallel with push (avoids ADB/device drop)
            if staged_images:
                time.sleep(IMAGE_PUSH_HEAD_START_SECONDS)

            # Run UI FSM
            fsm.run()

            # Archive staging directory (phone images will be cleaned up on next post)
            archive_path = archive_post(post_id)
            duration_ms = int(time.monotonic() * 1000) - start_ms
            log_submit_success(post_id, duration_ms)

            return {"status": "success", "post_id": post_id, "archive_path": archive_path}

        except FsmError as exc:
            log_submit_failure(post_id, str(exc), plan.current_state.value)
            return {
                "status": "failed",
                "post_id": post_id,
                "error": str(exc),
                "fsm_state": plan.current_state.value,
            }

        except Exception as exc:
            log_submit_failure(post_id, str(exc), plan.current_state.value)
            raise
    finally:
        _release_lock()


def _handle_crash_recovery(post_id: str) -> dict:
    """
    Called when a previous submit attempt left status='submitting'.
    Checks current WeChat screen to decide if post was already published or can be retried.

    Safe to retry states (post was NOT submitted):
    - MOMENTS_COMPOSE: still on compose screen
    - CAMERA_BOTTOM_SHEET: camera options menu open
    - ALBUM_PICKER, ALBUM_DROPDOWN, ALBUM_FILTER: in album selection flow
    - MOMENTS_FEED: back on feed, can restart
    - DISCOVER_PAGE, WECHAT_MAIN: can restart from beginning

    Possibly submitted states (cannot safely retry):
    - DONE: explicitly finished
    - Any other unknown state
    """
    try:
        adb = ADB.auto_connect()
        screenshot = adb.screenshot()
        ui_tree = adb.dump_ui()
        current_state = _identify_state(ui_tree, screenshot)

        # States where we know the post was NOT submitted - safe to retry
        safe_to_retry_states = {
            UiState.MOMENTS_COMPOSE,
            UiState.INPUT_TEXT,
            UiState.CAMERA_BOTTOM_SHEET,
            UiState.ALBUM_PICKER,
            UiState.ALBUM_DROPDOWN,
            UiState.ALBUM_FILTER,
            UiState.MOMENTS_FEED,
            UiState.DISCOVER_PAGE,
            UiState.WECHAT_MAIN,
            UiState.LAUNCH_WECHAT,
            UiState.DISCARD_DIALOG,
            UiState.LONG_TEXT_COMPOSE,
        }

        if current_state in safe_to_retry_states:
            # Post was NOT submitted; safe to retry
            update_meta_status(post_id, "prepared")
            return execute_submit(post_id)
        else:
            reason = f"WeChat is in state {current_state.value}, cannot safely determine if post was submitted"
            log_possibly_submitted(post_id, reason)
            return {
                "status": "possibly_submitted",
                "post_id": post_id,
                "message": "post may have been published in a previous attempt; "
                f"WeChat is in state {current_state.value}",
            }
    except Exception as exc:
        return {"status": "failed", "post_id": post_id, "error": f"crash recovery failed: {exc}"}
