import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .config import WECHAT_PACKAGE


@dataclass
class UINode:
    text: str
    content_desc: str
    resource_id: str
    class_name: str
    bounds: tuple[int, int, int, int]  # left, top, right, bottom
    selected: bool
    clickable: bool
    children: list["UINode"]

    @property
    def center(self) -> tuple[int, int]:
        x = (self.bounds[0] + self.bounds[2]) // 2
        y = (self.bounds[1] + self.bounds[3]) // 2
        return x, y


def _parse_bounds(bounds_str: str) -> tuple[int, int, int, int]:
    # Format: "[left,top][right,bottom]"
    parts = bounds_str.replace("][", ",").strip("[]").split(",")
    return int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])


def _parse_node(element: ET.Element) -> UINode:
    bounds_str = element.attrib.get("bounds", "[0,0][0,0]")
    children = [_parse_node(child) for child in element]
    return UINode(
        text=element.attrib.get("text", ""),
        content_desc=element.attrib.get("content-desc", ""),
        resource_id=element.attrib.get("resource-id", ""),
        class_name=element.attrib.get("class", ""),
        bounds=_parse_bounds(bounds_str),
        selected=element.attrib.get("selected", "false") == "true",
        clickable=element.attrib.get("clickable", "false") == "true",
        children=children,
    )


def find_node(
    root: UINode,
    text: str | None = None,
    content_desc: str | None = None,
    class_name: str | None = None,
    selected: bool | None = None,
) -> UINode | None:
    """Recursively search for a node matching all provided criteria."""
    match = True
    if text is not None and text not in root.text:
        match = False
    if content_desc is not None and content_desc not in root.content_desc:
        match = False
    if class_name is not None and class_name not in root.class_name:
        match = False
    if selected is not None and root.selected != selected:
        match = False
    if match:
        return root
    for child in root.children:
        result = find_node(
            child, text=text, content_desc=content_desc, class_name=class_name, selected=selected
        )
        if result is not None:
            return result
    return None


def find_all_nodes(
    root: UINode,
    text: str | None = None,
    content_desc: str | None = None,
    class_name: str | None = None,
) -> list[UINode]:
    """Return all nodes matching all provided criteria."""
    results = []
    match = True
    if text is not None and text not in root.text:
        match = False
    if content_desc is not None and content_desc not in root.content_desc:
        match = False
    if class_name is not None and class_name not in root.class_name:
        match = False
    if match:
        results.append(root)
    for child in root.children:
        results.extend(
            find_all_nodes(child, text=text, content_desc=content_desc, class_name=class_name)
        )
    return results


class ADB:
    def __init__(self, serial: str | None = None):
        self.serial = serial
        self._base = ["adb"]
        if serial:
            self._base += ["-s", serial]
        self._lock = threading.Lock()

    def _run(
        self, args: list[str], check: bool = True, timeout: int = 30
    ) -> subprocess.CompletedProcess:
        cmd = self._base + args
        with self._lock:
            return subprocess.run(cmd, capture_output=True, text=True, check=check, timeout=timeout)

    def _run_binary(
        self, args: list[str], check: bool = True, timeout: int = 30
    ) -> subprocess.CompletedProcess:
        """Run adb and return stdout as bytes (for screencap, etc.)."""
        cmd = self._base + args
        with self._lock:
            return subprocess.run(
                cmd, capture_output=True, text=False, check=check, timeout=timeout
            )

    # --- Device management ---

    @classmethod
    def get_connected_serials(cls) -> list[str]:
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
        serials = []
        for line in result.stdout.splitlines()[1:]:
            line = line.strip()
            if line and not line.startswith("*") and "\t" in line:
                serial, state = line.split("\t", 1)
                if state.strip() == "device":
                    serials.append(serial.strip())
        return serials

    @classmethod
    def auto_connect(cls) -> "ADB":
        """Connect to the first available device."""
        serials = cls.get_connected_serials()
        if not serials:
            raise RuntimeError(
                "No device connected. Connect your phone via USB and run 'adb devices' to confirm it is listed."
            )
        return cls(serial=serials[0])

    def get_serial(self) -> str:
        if self.serial:
            return self.serial
        serials = self.get_connected_serials()
        if not serials:
            raise RuntimeError(
                "No device connected. Connect your phone via USB and run 'adb devices' to confirm it is listed."
            )
        self.serial = serials[0]
        self._base = ["adb", "-s", self.serial]
        return self.serial

    def is_device_connected(self) -> bool:
        """Return False if no device or current serial is no longer in adb devices."""
        serials = self.get_connected_serials()
        if not serials:
            return False
        if self.serial is not None:
            return self.serial in serials
        return True

    def restart_server(self) -> None:
        """Restart ADB server to recover from connection issues."""
        subprocess.run(["adb", "kill-server"], capture_output=True, timeout=10)
        time.sleep(0.5)
        subprocess.run(["adb", "start-server"], capture_output=True, timeout=10)
        time.sleep(1.0)
        # Clear cached serial so it gets re-detected
        self.serial = None
        self._base = ["adb"]

    # --- Screen ---

    _SCREENSHOT_TMP_PATH = "/data/local/tmp/_wmp_screen.png"

    def _get_display_id(self) -> str | None:
        """Query the first display ID from SurfaceFlinger. Returns None if unavailable."""
        try:
            result = self._run(
                ["shell", "dumpsys", "SurfaceFlinger", "--display-id"],
                check=False,
                timeout=10,
            )
            for line in result.stdout.splitlines():
                # Format: "Display <id> (HWC display N): ..."
                if line.startswith("Display "):
                    parts = line.split()
                    if len(parts) >= 2:
                        return parts[1]
        except Exception:
            pass
        return None

    def screenshot(self) -> bytes:
        """Capture screen and return PNG bytes.

        Strategy: single ``adb shell`` call that runs screencap **and** base64 in
        one command, so only one USB round-trip is needed per attempt.  This halves
        the number of ADB transport operations compared to the previous two-call
        approach and significantly reduces the chance of triggering the USB
        transport-reset bug on Honor / Huawei (EMUI/MagicOS) devices.

        Uses -d <display_id> when available to suppress multi-display warnings.
        Falls back to no -d if the display_id format is not supported.
        If all attempts fail, tries restarting ADB server once before giving up.
        """
        self.get_serial()  # ensure _base has -s
        display_id = self._get_display_id()
        server_restarted = False

        for attempt in range(4):  # 3 normal attempts + 1 after server restart
            if attempt > 0:
                time.sleep(0.5)

            # After 3 failed attempts, try restarting ADB server
            if attempt == 3 and not server_restarted:
                self.restart_server()
                server_restarted = True
                self.get_serial()  # re-detect device after restart
                display_id = self._get_display_id()

            # Build screencap command - try with display_id first, fallback without
            if display_id and attempt in (
                0,
                3,
            ):  # Try with display_id on first attempt and after restart
                screencap_cmd = f"screencap -d {display_id} {self._SCREENSHOT_TMP_PATH}"
            else:
                # Fallback: no -d parameter (for devices where display_id format is unsupported)
                screencap_cmd = f"screencap {self._SCREENSHOT_TMP_PATH}"
                display_id = None  # Don't retry with display_id

            # Single shell invocation: screencap && base64 in one USB round-trip.
            # This avoids releasing the ADB transport lock between the two
            # operations, which on Honor/Huawei devices can cause the transport
            # to enter a stale state and make the device disappear from
            # ``adb devices``.
            combined_cmd = f"{screencap_cmd} && base64 {self._SCREENSHOT_TMP_PATH}"

            try:
                result = self._run(
                    ["shell", combined_cmd],
                    timeout=30,
                    check=False,
                )
                if result.returncode != 0:
                    if display_id:
                        # Retry without -d parameter
                        display_id = None
                    continue

                data = __import__("base64").b64decode(result.stdout)
                if data and len(data) >= 100:
                    return data
            except Exception:
                if attempt >= 3:
                    raise
        raise RuntimeError(
            "screencap (shell+base64) failed after 4 attempts (including ADB server restart). "
            "Try reconnecting the device."
        )

    def screenshot_to_file(self, path: str | Path) -> None:
        """Capture screen and save to local file."""
        Path(path).write_bytes(self.screenshot())

    # --- UI tree ---

    def dump_ui(self) -> UINode:
        """Dump UI hierarchy and return parsed tree."""
        self._run(["shell", "uiautomator", "dump", "/sdcard/_wmp_ui.xml"])
        result = self._run(["shell", "cat", "/sdcard/_wmp_ui.xml"])
        self._run(["shell", "rm", "-f", "/sdcard/_wmp_ui.xml"])
        xml_str = result.stdout.strip()
        if not xml_str or "<" not in xml_str:
            raise RuntimeError(
                f"uiautomator dump returned empty output. Raw: {repr(xml_str[:200])}"
            )
        try:
            root_el = ET.fromstring(xml_str)
        except ET.ParseError as exc:
            raise RuntimeError(
                f"Failed to parse UI XML: {exc}\nRaw (first 500): {xml_str[:500]}"
            ) from exc
        # uiautomator dump wraps in <hierarchy>, actual root is first child
        first_child = list(root_el)[0] if list(root_el) else root_el
        return _parse_node(first_child)

    def dump_ui_to_file(self, path: str | Path) -> UINode:
        """Dump UI hierarchy, save XML to file, and return parsed tree."""
        self._run(["shell", "uiautomator", "dump", "/sdcard/_wmp_ui.xml"])
        self._run(["pull", "/sdcard/_wmp_ui.xml", str(path)])
        self._run(["shell", "rm", "/sdcard/_wmp_ui.xml"])
        xml_str = Path(path).read_text(encoding="utf-8")
        root_el = ET.fromstring(xml_str)
        first_child = list(root_el)[0] if list(root_el) else root_el
        return _parse_node(first_child)

    # --- Input ---

    def tap(self, x: int, y: int) -> None:
        self._run(["shell", "input", "tap", str(x), str(y)])

    def long_press(self, x: int, y: int, duration_ms: int = 1000) -> None:
        self._run(["shell", "input", "swipe", str(x), str(y), str(x), str(y), str(duration_ms)])

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        """Swipe from (x1, y1) to (x2, y2). Used e.g. to scroll list."""
        self._run(
            [
                "shell",
                "input",
                "swipe",
                str(x1),
                str(y1),
                str(x2),
                str(y2),
                str(duration_ms),
            ]
        )

    def press_back(self) -> None:
        self._run(["shell", "input", "keyevent", "KEYCODE_BACK"])

    def tap_node(self, node: UINode) -> None:
        x, y = node.center
        self.tap(x, y)

    # --- App lifecycle ---

    def start_app(self, package: str = WECHAT_PACKAGE) -> None:
        self._run(["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"])

    def force_stop(self, package: str = WECHAT_PACKAGE) -> None:
        self._run(["shell", "am", "force-stop", package])

    def restart_app(self, package: str = WECHAT_PACKAGE) -> None:
        self.force_stop(package)
        time.sleep(1)
        self.start_app(package)

    def is_app_installed(self, package: str) -> bool:
        result = self._run(["shell", "pm", "list", "packages", package], check=False)
        return f"package:{package}" in result.stdout

    # --- File operations ---

    def push_file(self, local_path: str | Path, remote_path: str) -> None:
        self._run(["push", str(local_path), remote_path], timeout=120)

    def shell(self, cmd: str) -> str:
        result = self._run(["shell", cmd])
        return result.stdout.strip()

    def list_files(self, remote_dir: str) -> list[str]:
        result = self._run(["shell", f"ls {remote_dir}"], check=False)
        if result.returncode != 0:
            return []
        return [f.strip() for f in result.stdout.splitlines() if f.strip()]

    def mkdir(self, remote_dir: str) -> None:
        self._run(["shell", "mkdir", "-p", remote_dir])

    def rm_dir_contents(self, remote_dir: str) -> None:
        self._run(["shell", f"rm -f {remote_dir}/*"], check=False)

    def broadcast_media_scan(self, remote_dir: str) -> None:
        self._run(
            [
                "shell",
                "am",
                "broadcast",
                "-a",
                "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                "-d",
                f"file://{remote_dir}",
            ]
        )

    # --- IME ---

    def get_current_ime(self) -> str:
        return self.shell("settings get secure default_input_method")

    def set_ime(self, ime: str) -> None:
        self._run(["shell", "ime", "set", ime])

    def input_text_adbkeyboard(self, text: str) -> None:
        escaped = text.replace("'", "'\\''")
        self._run(["shell", f"am broadcast -a ADB_INPUT_TEXT --es msg '{escaped}'"])

    def wait(self, ms: int) -> None:
        time.sleep(ms / 1000)

    # --- Screen power ---

    def is_screen_on(self) -> bool:
        result = self._run(["shell", "dumpsys", "power"], check=False)
        return "mHoldingDisplaySuspendBlocker=true" in result.stdout

    def get_foreground_package(self) -> str:
        """Return the package name of the currently focused app."""
        result = self._run(
            ["shell", "dumpsys", "activity", "activities"],
            check=False,
        )
        for line in result.stdout.splitlines():
            if "mResumedActivity" in line or "ResumedActivity" in line:
                # line looks like: mResumedActivity: ActivityRecord{... com.tencent.mm/.ui.LauncherUI ...}
                parts = line.strip().split()
                for part in parts:
                    if "/" in part and not part.startswith("{"):
                        return part.split("/")[0]
        return ""

    def get_current_activity(self) -> str:
        """
        Return the short class name of the currently resumed Activity.
        E.g. 'LauncherUI', 'SnsTimeLineUI', 'SnsUploadUI'.
        Returns empty string if not found.
        """
        result = self._run(
            ["shell", "dumpsys", "activity", "activities"],
            check=False,
        )
        for line in result.stdout.splitlines():
            if (
                "topResumedActivity" in line
                or "mResumedActivity" in line
                or "ResumedActivity" in line
            ):
                # line: topResumedActivity=ActivityRecord{... com.tencent.mm/.plugin.sns.ui.SnsUploadUI t265}
                # or:   mResumedActivity: ActivityRecord{... com.tencent.mm/.ui.LauncherUI ...}
                parts = line.strip().split()
                for part in parts:
                    if "/" in part and not part.startswith("{"):
                        # part: com.tencent.mm/.plugin.sns.ui.SnsUploadUI or com.tencent.mm/.ui.LauncherUI
                        activity_full = part.split("/")[-1]
                        # Remove trailing non-identifier chars (e.g. "t265}")
                        activity_full = activity_full.split()[0].rstrip("}")
                        # Extract short class name (after last dot)
                        short_name = activity_full.split(".")[-1]
                        return short_name
        return ""

    def wait_for_package(self, package: str, timeout: float = 20.0, interval: float = 0.8) -> bool:
        """Wait until `package` is the foreground app."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.get_foreground_package() == package:
                return True
            time.sleep(interval)
        return False

    def wake_screen(self) -> None:
        """Wake up screen and dismiss lock screen."""
        if not self.is_screen_on():
            self._run(["shell", "input", "keyevent", "KEYCODE_WAKEUP"])
            time.sleep(0.5)

        # Dismiss keyguard (lock screen) directly
        self._run(["shell", "wm", "dismiss-keyguard"])
        time.sleep(0.3)
