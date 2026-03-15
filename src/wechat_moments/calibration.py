import json

from pydantic import BaseModel

from .config import PROFILES_DIR


class UIProfile(BaseModel):
    device_id: str
    screen_width: int = 1080
    screen_height: int = 2340

    # Tab bar Y position (pixels)
    tab_bar_y: int = 2200

    # Discover page: "朋友圈" entry position (pixels)
    moments_entry_x: int = 540
    moments_entry_y: int = 135

    # Moments feed: camera button position (pixels)
    moments_camera_x: int = 1015
    moments_camera_y: int = 130

    # Album grid: first cell selection circle and grid spacing (pixels)
    album_grid_first_x: int = 243
    album_grid_first_y: int = 317
    album_grid_col_width: int = 295
    album_grid_row_height: int = 295

    # Album picker: "从相册选择" button Y position (pixels)
    album_picker_y: int = 1685

    # Album picker: "完成" button position (pixels) - in BOTTOM bar, not top (top has 搜索)
    album_done_x: int = 1005
    album_done_y: int = 2200  # Bottom bar; was 152 (top) which caused tapping 搜索

    # Album picker: dropdown button position (pixels) - "图片和视频 ▼"
    album_dropdown_x: int = 230
    album_dropdown_y: int = 75

    # Album picker: WeChatMCP album position in dropdown list (pixels)
    album_wechatmcp_x: int = 200
    album_wechatmcp_y: int = 400  # Approximate, needs calibration

    # Compose screen: text input tap area (pixels)
    compose_text_x: int = 324
    compose_text_y: int = 585

    # Compose screen: "发表" submit button (pixels)
    compose_submit_x: int = 1005
    compose_submit_y: int = 152

    # Discard dialog: "不保留" abandon button (pixels)
    discard_abandon_x: int = 270
    discard_abandon_y: int = 1287

    # Discard dialog: "保留" keep button (pixels)
    discard_keep_x: int = 810
    discard_keep_y: int = 1287

    # Long text compose: text input area (pixels)
    long_text_text_x: int = 540
    long_text_text_y: int = 234

    # Long text compose: submit button (pixels)
    long_text_submit_x: int = 1005
    long_text_submit_y: int = 152

    def tab_coords(self, tab_index: int, num_tabs: int = 4) -> tuple[int, int]:
        """Return absolute tap coords for tab at given index (0-based)."""
        x = int(self.screen_width * (tab_index + 0.5) / num_tabs)
        y = self.tab_bar_y
        return x, y

    def album_cell_coords(self, index: int) -> tuple[int, int]:
        """Return coords for album cell selection circle."""
        cols = 4
        row = index // cols
        col = index % cols
        x = self.album_grid_first_x + col * self.album_grid_col_width
        y = self.album_grid_first_y + row * self.album_grid_row_height
        return x, y

    def camera_coords(self) -> tuple[int, int]:
        """Return absolute coords for the camera button on Moments feed."""
        return self.moments_camera_x, self.moments_camera_y

    def moments_entry_coords(self) -> tuple[int, int]:
        """Return absolute coords for '朋友圈' entry on Discover page."""
        return self.moments_entry_x, self.moments_entry_y

    def album_option_coords(self) -> tuple[int, int]:
        """Return absolute coords for '从相册选择' in bottom sheet."""
        return self.screen_width // 2, self.album_picker_y

    def album_done_coords(self) -> tuple[int, int]:
        """Return absolute coords for '完成' button in album picker."""
        return self.album_done_x, self.album_done_y

    def album_dropdown_coords(self) -> tuple[int, int]:
        """Return absolute coords for album dropdown button."""
        return self.album_dropdown_x, self.album_dropdown_y

    def album_wechatmcp_coords(self) -> tuple[int, int]:
        """Return absolute coords for WeChatMCP album in dropdown list."""
        return self.album_wechatmcp_x, self.album_wechatmcp_y

    def compose_text_coords(self) -> tuple[int, int]:
        """Return absolute coords for text input area in compose screen."""
        return self.compose_text_x, self.compose_text_y

    def compose_submit_coords(self) -> tuple[int, int]:
        """Return absolute coords for '发表' button in compose screen."""
        return self.compose_submit_x, self.compose_submit_y

    def discard_abandon_coords(self) -> tuple[int, int]:
        """Return absolute coords for '不保留' button in discard dialog."""
        return self.discard_abandon_x, self.discard_abandon_y

    def discard_keep_coords(self) -> tuple[int, int]:
        """Return absolute coords for '保留' button in discard dialog."""
        return self.discard_keep_x, self.discard_keep_y

    def long_text_submit_coords(self) -> tuple[int, int]:
        """Return absolute coords for submit button in long text compose."""
        return self.long_text_submit_x, self.long_text_submit_y

    def long_text_text_coords(self) -> tuple[int, int]:
        """Return absolute coords for text input area in long text compose."""
        return self.long_text_text_x, self.long_text_text_y


def load_profile(device_id: str) -> UIProfile:
    """Load device profile, falling back to huawei_default if not found."""
    device_path = PROFILES_DIR / f"{device_id}.json"
    default_path = PROFILES_DIR / "huawei_default.json"

    for path in (device_path, default_path):
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            data["device_id"] = device_id
            return UIProfile(**data)

    # No profile at all: return defaults
    return UIProfile(device_id=device_id)


def save_profile(profile: UIProfile) -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    path = PROFILES_DIR / f"{profile.device_id}.json"
    data = profile.model_dump()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
