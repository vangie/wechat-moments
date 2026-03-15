import tempfile
from pathlib import Path

import httpx

from .adb import ADB
from .config import ADBKEYBOARD_PACKAGE

ADBKEYBOARD_APK_URL = "https://github.com/senzhk/ADBKeyBoard/raw/master/ADBKeyboard.apk"


class ImeError(RuntimeError):
    pass


class ImeManager:
    def __init__(self, adb: ADB):
        self._adb = adb
        self._saved_ime: str | None = None

    def _download_apk(self) -> Path:
        """Download ADBKeyboard APK to temp directory."""
        apk_path = Path(tempfile.gettempdir()) / "ADBKeyboard.apk"
        if apk_path.exists():
            return apk_path

        response = httpx.get(ADBKEYBOARD_APK_URL, follow_redirects=True, timeout=60)
        response.raise_for_status()
        apk_path.write_bytes(response.content)
        return apk_path

    def _install_adbkeyboard(self) -> None:
        """Download and install ADBKeyboard on the device."""
        apk_path = self._download_apk()
        self._adb._run(["install", "-r", str(apk_path)])

    def ensure_adbkeyboard_installed(self) -> None:
        package = ADBKEYBOARD_PACKAGE.split("/")[0]
        if not self._adb.is_app_installed(package):
            self._install_adbkeyboard()
            if not self._adb.is_app_installed(package):
                raise ImeError(
                    f"Failed to install ADBKeyboard automatically.\n"
                    f"Please install it manually:\n"
                    f"  curl -L {ADBKEYBOARD_APK_URL} -o /tmp/ADBKeyboard.apk\n"
                    f"  adb install /tmp/ADBKeyboard.apk"
                )

    def save_and_switch(self) -> None:
        """Save current IME and switch to ADBKeyboard."""
        self.ensure_adbkeyboard_installed()
        self._saved_ime = self._adb.get_current_ime()
        self._adb.set_ime(ADBKEYBOARD_PACKAGE)

    def restore(self) -> None:
        """Restore the previously saved IME."""
        if self._saved_ime:
            self._adb.set_ime(self._saved_ime)
            self._saved_ime = None

    def input_text(self, text: str) -> None:
        """
        Input text using ADBKeyboard broadcast.
        Must call save_and_switch() before this.
        """
        self._adb.input_text_adbkeyboard(text)

    def input_with_ime_switch(self, text: str) -> bool:
        """
        Convenience: switch IME, input text, restore IME.
        Returns True if successful, False if failed.
        """
        self.save_and_switch()
        try:
            self.input_text(text)
            return True
        except Exception:
            return False
        finally:
            self.restore()
