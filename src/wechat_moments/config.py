import os
from pathlib import Path


def _find_project_root() -> Path | None:
    """Find project root (directory containing pyproject.toml or .env), from cwd upward."""
    try:
        cwd = Path.cwd().resolve()
    except RuntimeError:
        return None
    for p in [cwd] + list(cwd.parents)[:5]:
        if (p / "pyproject.toml").exists() or (p / ".env").exists():
            return p
    return None


def _load_env_file(path: Path, override: bool = False) -> None:
    """Load KEY=VALUE lines from path into os.environ. If not override, skip keys already set."""
    if not path.is_file():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                key = k.strip()
                if key and (override or key not in os.environ):
                    os.environ[key] = v.strip()
    except OSError:
        pass


def _load_dotenv() -> None:
    """Load .env then .env.local from project root or cwd. .env.local overrides .env."""
    root = _find_project_root()
    for d in [root, Path.cwd()] if root else [Path.cwd()]:
        if d is None:
            continue
        _load_env_file(d / ".env", override=False)
        _load_env_file(d / ".env.local", override=True)
        break


_load_dotenv()

DATA_DIR = Path.home() / ".local" / "share" / "wechat-moments"
STAGING_DIR = DATA_DIR / "staging"
# Debug output base dir: when WECHAT_POSTER_DEBUG_DIR is set (in .env or .env.local),
# --debug writes timestamped run dirs under it. Relative path = under project root.
_debug_dir_raw = os.environ.get("WECHAT_POSTER_DEBUG_DIR", "").strip()
_PROJECT_ROOT = _find_project_root()
if _debug_dir_raw and _PROJECT_ROOT:
    _p = Path(_debug_dir_raw)
    DEBUG_BASE_DIR = _p if _p.is_absolute() else (_PROJECT_ROOT / _p)
else:
    DEBUG_BASE_DIR = DATA_DIR / "debug"
ARCHIVE_DIR = DATA_DIR / "archive"
HISTORY_FILE = DATA_DIR / "history.jsonl"
LOCK_FILE = DATA_DIR / "submit.lock"

# Profiles bundled inside the package (importlib.resources)
import importlib.resources as _pkg_resources

def _bundled_profiles_dir() -> Path:
    """Return the path to bundled profiles shipped inside the wheel."""
    return Path(str(_pkg_resources.files("wechat_moments.profiles")))

PROFILES_DIR = _bundled_profiles_dir()

WECHAT_PACKAGE = "com.tencent.mm"
PHONE_IMAGE_DIR = "/sdcard/DCIM/WeChatMCP"

STAGING_EXPIRE_HOURS = 1
ARCHIVE_EXPIRE_DAYS = 30

FSM_MAX_STEPS = 200
FSM_TIMEOUT_SECONDS = 300
FSM_UNKNOWN_TIMEOUT_SECONDS = 60
# Max FORCE_RESTART attempts before aborting (prevents infinite restart loops)
FSM_FORCE_RESTART_MAX = 3
# Cycle detection: if last 2*k states repeat (first k == second k), abort
FSM_CYCLE_WINDOW = 4
# Throttle to avoid overloading ADB (incomplete PNG / device drop)
SCREENSHOT_COOLDOWN_MS = 250  # ms to wait after screenshot before next adb call
FSM_STEP_DELAY_SECONDS = 0.7  # delay between FSM steps (was 0.5)
# Delay before UI FSM when images are pushing: avoid first screencap running in parallel with push
IMAGE_PUSH_HEAD_START_SECONDS = 2.0

IMAGE_FSM_MEDIA_SCAN_RETRIES = 3
IMAGE_FSM_MEDIA_SCAN_INTERVAL = 1.0

SELECT_IMAGES_CHECKMARK_RETRIES = 3
SELECT_IMAGES_WAIT_MS = 500

# Album dropdown: max scroll retries when WeChatMCP is not on first screen
ALBUM_DROPDOWN_SCROLL_RETRIES = 5
ALBUM_DROPDOWN_SCROLL_WAIT_MS = 400

ADBKEYBOARD_PACKAGE = "com.android.adbkeyboard/.AdbIME"

# Display name shown in post preview (set via WECHAT_DISPLAY_NAME in .env.local)
WECHAT_DISPLAY_NAME: str = os.environ.get("WECHAT_DISPLAY_NAME", "我")
