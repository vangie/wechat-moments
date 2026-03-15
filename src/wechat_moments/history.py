"""
history.jsonl structured event logging.
"""

import json
from datetime import UTC, datetime
from typing import Any

from .config import DATA_DIR, HISTORY_FILE


def _log(event: str, **fields: Any) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "event": event,
        **fields,
    }
    with HISTORY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def log_prepare_post(post_id: str, text_length: int, image_count: int) -> None:
    _log("prepare_post", post_id=post_id, text_length=text_length, image_count=image_count)


def log_submit_start(post_id: str) -> None:
    _log("submit_start", post_id=post_id)


def log_submit_success(post_id: str, duration_ms: int) -> None:
    _log("submit_success", post_id=post_id, duration_ms=duration_ms)


def log_submit_failure(post_id: str, error: str, fsm_state: str) -> None:
    _log("submit_failure", post_id=post_id, error=error, fsm_state=fsm_state)


def log_lock_rejected(rejected_post_id: str, active_post_id: str) -> None:
    _log("lock_rejected", rejected_post_id=rejected_post_id, active_post_id=active_post_id)


def log_possibly_submitted(post_id: str, reason: str) -> None:
    _log("possibly_submitted", post_id=post_id, reason=reason)
