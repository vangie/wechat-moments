import threading
import time
from enum import Enum
from pathlib import Path

from .adb import ADB
from .config import (
    IMAGE_FSM_MEDIA_SCAN_INTERVAL,
    IMAGE_FSM_MEDIA_SCAN_RETRIES,
    PHONE_IMAGE_DIR,
)


class ImageState(Enum):
    IDLE = "idle"
    PUSHING = "pushing"
    SCANNING = "scanning"
    READY = "ready"
    CLEANUP = "cleanup"
    ERROR = "error"


class ImageFSMError(RuntimeError):
    pass


class ImageFSM:
    """
    Background FSM that pushes images to the phone concurrently with UI navigation.
    Signals ready_event when images are confirmed present on device.
    """

    def __init__(self, adb: ADB, image_paths: list[Path]):
        self._adb = adb
        self._image_paths = image_paths
        self.state = ImageState.IDLE
        self.ready_event = threading.Event()
        self.error: str | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self._image_paths:
            # No images: signal ready immediately, nothing to push
            self.state = ImageState.READY
            self.ready_event.set()
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="ImageFSM")
        self._thread.start()

    def _run(self) -> None:
        try:
            self._push()
            self._scan()
            self.state = ImageState.READY
            self.ready_event.set()
        except Exception as exc:
            self.state = ImageState.ERROR
            self.error = str(exc)
            # Still set the event so UI FSM doesn't block forever; it will check state
            self.ready_event.set()

    def _push(self) -> None:
        self.state = ImageState.PUSHING
        self._adb.mkdir(PHONE_IMAGE_DIR)
        self._adb.rm_dir_contents(PHONE_IMAGE_DIR)
        for i, path in enumerate(self._image_paths):
            suffix = path.suffix or ".jpg"
            remote = f"{PHONE_IMAGE_DIR}/IMG_{i + 1:04d}{suffix}"
            self._adb.push_file(path, remote)

    def _scan(self) -> None:
        self.state = ImageState.SCANNING
        self._adb.broadcast_media_scan(PHONE_IMAGE_DIR)
        expected = len(self._image_paths)
        for attempt in range(IMAGE_FSM_MEDIA_SCAN_RETRIES):
            files = self._adb.list_files(PHONE_IMAGE_DIR)
            if len(files) >= expected:
                return
            if attempt < IMAGE_FSM_MEDIA_SCAN_RETRIES - 1:
                time.sleep(IMAGE_FSM_MEDIA_SCAN_INTERVAL)
        raise ImageFSMError(
            f"Media scan failed: expected {expected} files in {PHONE_IMAGE_DIR}, "
            f"found {len(self._adb.list_files(PHONE_IMAGE_DIR))}"
        )

    def trigger_cleanup(self) -> None:
        if not self._image_paths:
            return
        self.state = ImageState.CLEANUP
        self._adb.rm_dir_contents(PHONE_IMAGE_DIR)
        self._adb.broadcast_media_scan(PHONE_IMAGE_DIR)

    def wait_until_ready(self, timeout: float = 60.0) -> None:
        if not self.ready_event.wait(timeout=timeout):
            raise ImageFSMError("Image FSM timed out waiting to become READY")
        if self.state == ImageState.ERROR:
            raise ImageFSMError(f"Image FSM failed: {self.error}")
