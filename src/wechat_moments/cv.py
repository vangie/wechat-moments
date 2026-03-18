import cv2
import numpy as np
from PIL import Image

try:
    import pytesseract
    from pytesseract import Output

    _PYTESSERACT_AVAILABLE = True
except ImportError:
    _PYTESSERACT_AVAILABLE = False


def _bytes_to_cv2(image_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(
            "Invalid or incomplete PNG (e.g. screenshot stream truncated). "
            "Try again or check device/USB connection."
        )
    return img


def _cv2_to_png_bytes(img: np.ndarray) -> bytes:
    _, buf = cv2.imencode(".png", img)
    return buf.tobytes()


def annotate_screenshot_for_debug(
    screenshot_bytes: bytes,
    tap_xy: tuple[int, int] | None,
    tap_label: str = "",
) -> bytes:
    """
    Draw tap point, ROI rectangle, and scale ticks on a screenshot for debugging.
    tap_xy: (x, y) where we will tap; if None, only ROI and scale are drawn.
    tap_label: e.g. "green" or "profile" to show in the label.
    Returns PNG bytes of the annotated image.
    """
    img = _bytes_to_cv2(screenshot_bytes).copy()
    h, w = img.shape[:2]

    # Scale ticks: left edge (vertical) and bottom edge (horizontal), 0/25/50/75/100%
    tick_len = max(4, min(w, h) // 80)
    color_scale = (180, 180, 180)  # light gray
    for pct in (0, 25, 50, 75, 100):
        # Vertical tick on left
        x = 0
        y = int(h * pct / 100)
        cv2.line(img, (x, y), (x + tick_len, y), color_scale, 1)
        # Horizontal tick on bottom
        x = int(w * pct / 100)
        y = h - 1
        cv2.line(img, (x, y), (x, y - tick_len), color_scale, 1)
    # Percentage labels (small, at corners to avoid clutter)
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.35
    for pct in (0, 50, 100):
        cv2.putText(img, f"{pct}%", (2, int(h * pct / 100) - 2), font, font_scale, color_scale, 1)
        cv2.putText(
            img, f"{pct}%", (int(w * pct / 100) + 2, h - 4), font, font_scale, color_scale, 1
        )

    # ROI rectangle: bottom 12%, right half (green detection region)
    y1_roi = int(h * 0.88)
    x1_roi = int(w * 0.5)
    cv2.rectangle(img, (x1_roi, y1_roi), (w - 1, h - 1), (0, 255, 255), 1)  # yellow
    cv2.putText(img, "ROI(green)", (x1_roi, y1_roi - 2), font, font_scale, (0, 255, 255), 1)

    # Step/state label (top-left) when tap_xy is None; or tap point + label
    if tap_xy is not None:
        x, y = tap_xy
        color_tap = (0, 255, 255)  # cyan in BGR
        r = max(12, min(w, h) // 40)
        cv2.circle(img, (x, y), r, color_tap, 2)
        cv2.line(img, (x - r - 4, y), (x + r + 4, y), color_tap, 2)
        cv2.line(img, (x, y - r - 4), (x, y + r + 4), color_tap, 2)
        label = f"tap ({x},{y}) {tap_label}"
        cv2.putText(img, label, (x + r + 6, y + 4), font, 0.5, color_tap, 1)
    elif tap_label:
        # Step/state only (no tap)
        cv2.putText(img, tap_label, (8, int(h * 0.04)), font, 0.6, (0, 255, 255), 2)

    return _cv2_to_png_bytes(img)


def _file_to_cv2(path: str) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


# --- Tab bar detection ---


def detect_active_tab(screenshot_bytes: bytes) -> str | None:
    """
    Detect which bottom tab is active by comparing icon brightness in the tab bar region.
    Returns one of: 'wechat', 'contacts', 'discover', 'me', or None if undetectable.

    Strategy: The active tab icon is colored (higher saturation / brighter), while
    inactive tabs are grey. We crop the bottom tab bar, split into 4 equal columns,
    and check the average saturation of each section.
    """
    img = _bytes_to_cv2(screenshot_bytes)
    h, w = img.shape[:2]

    # Tab bar occupies the bottom ~10% of screen
    tab_bar = img[int(h * 0.90) : h, :]
    hsv = cv2.cvtColor(tab_bar, cv2.COLOR_BGR2HSV)

    tab_w = w // 4
    tabs = ["wechat", "contacts", "discover", "me"]
    saturations = []

    for i in range(4):
        section = hsv[:, i * tab_w : (i + 1) * tab_w]
        # Average saturation: active tab has higher saturation (colored icon)
        avg_sat = float(np.mean(section[:, :, 1]))
        saturations.append(avg_sat)

    max_idx = int(np.argmax(saturations))
    # Require a meaningful difference vs others to avoid false positives
    max_sat = saturations[max_idx]
    others = [s for j, s in enumerate(saturations) if j != max_idx]
    if max_sat - max(others) < 2:
        return None

    return tabs[max_idx]


def has_tab_bar(screenshot_bytes: bytes) -> bool:
    """
    Detect if the bottom tab bar is visible (WeChat main screen).

    Strategy: Check if the bottom 8% has the characteristic WeChat green color
    in one of the tabs (active tab indicator).

    Uses ratio-based thresholds for resolution independence.
    """
    img = _bytes_to_cv2(screenshot_bytes)
    h, w = img.shape[:2]

    # Tab bar region: bottom 8%
    tab_bar = img[int(h * 0.92) : h, :]

    # Check for green color (active tab indicator)
    hsv = cv2.cvtColor(tab_bar, cv2.COLOR_BGR2HSV)
    lower_green = np.array([35, 50, 50])
    upper_green = np.array([85, 255, 255])
    mask = cv2.inRange(hsv, lower_green, upper_green)

    # Use ratio instead of absolute pixel count
    green_ratio = float(np.sum(mask > 0)) / mask.size

    # Tab bar should have some green pixels (active tab)
    # and the region should be relatively bright (white background)
    gray = cv2.cvtColor(tab_bar, cv2.COLOR_BGR2GRAY)
    avg_brightness = float(np.mean(gray))

    # Green ratio > 0.5% of tab bar area indicates active tab
    return green_ratio > 0.005 and avg_brightness > 200


def count_green_checkmarks(
    screenshot_bytes: bytes, roi: tuple[int, int, int, int] | None = None
) -> int:
    """
    Count green checkmark circles in the image (WeChat album selection indicators).

    roi: (x, y, w, h) region of interest in pixels; if None, uses album grid region
         (5%-75% height to exclude header and bottom bar).

    Strategy: Mask pixels in HSV green range, find contours of circular shapes,
    filter by area ratio to avoid noise.

    Uses ratio-based thresholds for resolution independence.
    """
    img = _bytes_to_cv2(screenshot_bytes)
    h, w = img.shape[:2]

    # Default ROI: album grid region (exclude header ~5% and bottom bar ~25%)
    if roi is None:
        roi = (0, int(h * 0.05), w, int(h * 0.70))

    x, y, rw, rh = roi
    img = img[y : y + rh, x : x + rw]
    total_area = rw * rh

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # Green range in HSV (WeChat checkmark is a bright green circle)
    lower_green = np.array([40, 80, 80])
    upper_green = np.array([90, 255, 255])
    mask = cv2.inRange(hsv, lower_green, upper_green)

    # Clean up noise
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Area thresholds as ratio of total image area
    # WeChat checkmarks are large green circles, roughly 0.1% to 0.3% of ROI area
    min_area = total_area * 0.001
    max_area = total_area * 0.003

    count = 0
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if min_area < area < max_area:
            # Circularity check: 4π*area/perimeter² ≈ 1 for circles
            # WeChat checkmarks are very circular (>0.7)
            perimeter = cv2.arcLength(cnt, True)
            if perimeter > 0:
                circularity = 4 * np.pi * area / (perimeter**2)
                if circularity > 0.7:
                    count += 1

    return count


def has_album_picker_bottom_bar_text(screenshot_bytes: bytes) -> bool:
    """
    Detect if the bottom bar contains "预览" or "制作视频" (album picker specific).
    Locale-dependent: not used in is_album_picker so detection works in any system language.
    """
    if not _PYTESSERACT_AVAILABLE:
        return False
    img = _bytes_to_cv2(screenshot_bytes)
    h, w = img.shape[:2]
    bottom_bar = img[int(h * 0.88) : h, :]
    gray = cv2.cvtColor(bottom_bar, cv2.COLOR_BGR2GRAY)
    pil_img = Image.fromarray(gray)
    try:
        data = pytesseract.image_to_data(pil_img, output_type=Output.DICT, lang="chi_sim+eng")
    except (pytesseract.TesseractNotFoundError, pytesseract.TesseractError, Exception):
        return False
    for word in data.get("text") or []:
        s = (word or "").strip()
        if "预览" in s or "制作视频" in s:
            return True
    return False


def _count_circular_contours_in_region(
    img_region: np.ndarray,
    mask: np.ndarray,
    area_min_ratio: float,
    area_max_ratio: float,
    circularity_min: float = 0.6,
) -> int:
    """Count contours in mask that are roughly circular (selection circles)."""
    total_area = mask.size
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = total_area * area_min_ratio
    max_area = total_area * area_max_ratio
    count = 0
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if not (min_area < area < max_area):
            continue
        perimeter = cv2.arcLength(cnt, True)
        if perimeter <= 0:
            continue
        circularity = 4 * np.pi * area / (perimeter**2)
        if circularity >= circularity_min:
            count += 1
    return count


def has_selection_circles_in_album_grid(screenshot_bytes: bytes) -> bool:
    """
    Detect if the grid area has selection circle indicators (green checkmarks or empty circles).
    Album picker shows a circle on each thumbnail; filter/category screen does not.
    """
    img = _bytes_to_cv2(screenshot_bytes)
    h, w = img.shape[:2]
    grid = img[int(h * 0.08) : int(h * 0.75), :]

    # Green circles (selected checkmarks)
    hsv = cv2.cvtColor(grid, cv2.COLOR_BGR2HSV)
    green_mask = cv2.inRange(hsv, np.array([40, 80, 80]), np.array([90, 255, 255]))
    green_mask = cv2.morphologyEx(green_mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n_green = _count_circular_contours_in_region(
        grid, green_mask, 0.0008, 0.004, circularity_min=0.65
    )

    # Bright/white circles (unselected ring indicators)
    gray = cv2.cvtColor(grid, cv2.COLOR_BGR2GRAY)
    _, bright = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
    bright = cv2.morphologyEx(bright, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n_bright = _count_circular_contours_in_region(grid, bright, 0.0005, 0.003, circularity_min=0.55)

    return (n_green + n_bright) >= 1


def has_image_thumbnails_in_compose(screenshot_bytes: bytes) -> bool:
    """
    Detect if the compose screen already has image thumbnails (stale content).
    Returns True if image grid area contains thumbnails beyond just the '+' button.
    This is used to detect leftover content from a previous unfinished post.

    Strategy: Check the image grid area (middle section of compose screen) for
    non-white pixel density. The '+' button area is mostly white/grey; actual
    image thumbnails have varied colors.
    """
    img = _bytes_to_cv2(screenshot_bytes)
    h, w = img.shape[:2]

    # Image grid sits roughly between 15%-40% height on the compose screen
    grid_region = img[int(h * 0.15) : int(h * 0.42), int(w * 0.02) : int(w * 0.98)]

    gray = cv2.cvtColor(grid_region, cv2.COLOR_BGR2GRAY)
    # Count pixels that are not near-white (images have varied pixel colors)
    non_white = np.sum(gray < 220)
    total = gray.size
    ratio = non_white / total

    # If more than 15% of grid pixels are non-white, likely has image content
    return bool(ratio > 0.15)


# --- Bottom sheet / dialog detection ---


def detect_bottom_sheet(screenshot_bytes: bytes) -> bool:
    """
    Detect if a bottom sheet modal is visible (e.g. camera options menu).

    Strategy: Bottom sheets have these characteristics:
    1. A bright white panel at the bottom (~35% of screen)
    2. A semi-transparent dark overlay above it
    3. The overlay should be UNIFORM (low variance) - this distinguishes it from
       normal content like photos which have high variance
    """
    img = _bytes_to_cv2(screenshot_bytes)
    h, w = img.shape[:2]

    # Bottom sheet region: bottom 35% of screen
    bottom_region = img[int(h * 0.65) : h, :]
    # Overlay region: 40%-60% of screen (should be darker if bottom sheet is present)
    overlay_region = img[int(h * 0.40) : int(h * 0.60), :]

    # Convert to grayscale
    bottom_gray = cv2.cvtColor(bottom_region, cv2.COLOR_BGR2GRAY)
    overlay_gray = cv2.cvtColor(overlay_region, cv2.COLOR_BGR2GRAY)

    bottom_brightness = float(np.mean(bottom_gray))
    overlay_brightness = float(np.mean(overlay_gray))

    # Key insight: a real overlay has LOW variance (uniform semi-transparent gray)
    # while normal content (photos, text) has HIGH variance
    overlay_variance = float(np.var(overlay_gray))

    # Bottom sheet conditions:
    # 1. Bright bottom (>170)
    # 2. Darker overlay above (contrast > 40)
    # 3. Overlay is uniform (variance < 2000) - photos typically have variance > 3000
    has_bright_bottom = bottom_brightness > 170
    has_dark_overlay = overlay_brightness < bottom_brightness - 40
    has_uniform_overlay = overlay_variance < 2000

    return has_bright_bottom and has_dark_overlay and has_uniform_overlay


def find_album_option_in_bottom_sheet(screenshot_bytes: bytes) -> tuple[int, int] | None:
    """
    Find the "从相册选择" (Select from Album) button in the camera bottom sheet.
    Returns (x, y) center in full image coordinates, or None if bottom sheet not detected.

    Strategy: First verify this is actually a bottom sheet (using detect_bottom_sheet),
    then detect the sheet boundaries by brightness contrast and use layout proportions
    to locate the middle option. No OCR required.

    WeChat bottom sheet layout (3 options):
    - "拍摄" (Take photo) with subtitle: top ~35%
    - "从相册选择" (Select from album): middle ~30% (center at ~50%)
    - "取消" (Cancel): bottom ~35%
    """
    # First verify this is actually a bottom sheet
    if not detect_bottom_sheet(screenshot_bytes):
        return None

    img = _bytes_to_cv2(screenshot_bytes)
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Find the top edge of the bottom sheet by scanning upward
    # Bottom sheet is bright (>150), overlay above is dark (<150)
    sheet_top = None
    for y in range(h - 1, int(h * 0.5), -1):
        row_brightness = float(np.mean(gray[y, :]))
        if row_brightness < 150:
            sheet_top = y + 1
            break

    if sheet_top is None:
        return None

    sheet_height = h - sheet_top

    # The "从相册选择" button center is at approximately 50% of sheet height
    album_y = sheet_top + int(sheet_height * 0.50)
    album_x = w // 2

    return (album_x, album_y)


def find_dropdown_button_in_album_picker(screenshot_bytes: bytes) -> tuple[int, int] | None:
    """
    Find the dropdown button ("图片和视频 ▼") in the album picker header.
    Returns (x, y) center in full image coordinates, or None if not in album picker.

    Strategy: The dropdown button is always in the center of the dark header bar,
    which is located at approximately 3-10% from the top of the screen.
    No OCR required - uses layout proportions.
    """
    # First verify this is actually an album picker
    if not is_album_picker(screenshot_bytes):
        return None

    img = _bytes_to_cv2(screenshot_bytes)
    h, w = img.shape[:2]

    # Header region: top 3-10% of screen (after status bar)
    header_y1 = int(h * 0.03)
    header_y2 = int(h * 0.10)

    # Dropdown button is in the center of the header
    dropdown_x = w // 2
    dropdown_y = (header_y1 + header_y2) // 2

    return (dropdown_x, dropdown_y)


def detect_center_dialog(screenshot_bytes: bytes) -> bool:
    """
    Detect if a center dialog is visible (e.g. discard confirmation dialog).

    Key characteristics of a real dialog:
    1. Semi-transparent dark overlay covers the ENTIRE screen
    2. The overlay creates UNIFORM gray regions on the left and right margins
    3. A bright white rectangular dialog box in the center

    Strategy: Check that the left and right margins have LOW variance (uniform overlay)
    and the center has a bright dialog box.
    """
    img = _bytes_to_cv2(screenshot_bytes)
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Check the left and right margins (should be uniform gray if overlay present)
    left_margin = gray[int(h * 0.30) : int(h * 0.70), int(w * 0.02) : int(w * 0.12)]
    right_margin = gray[int(h * 0.30) : int(h * 0.70), int(w * 0.88) : int(w * 0.98)]

    # Standard deviation - low means uniform (overlay), high means varied content
    left_std = float(np.std(left_margin))
    right_std = float(np.std(right_margin))

    # Mean brightness of margins
    left_mean = float(np.mean(left_margin))
    right_mean = float(np.mean(right_margin))

    # Center dialog region
    center_region = gray[int(h * 0.42) : int(h * 0.62), int(w * 0.15) : int(w * 0.85)]
    center_brightness = float(np.mean(center_region))

    # For a real dialog:
    # 1. Both margins should have LOW variance (< 50) - uniform overlay
    # 2. Both margins should be moderately dark (100-180) - overlay effect
    # 3. Center should be bright (> 200) - the dialog box

    is_left_uniform = left_std < 50 and 100 < left_mean < 180
    is_right_uniform = right_std < 50 and 100 < right_mean < 180
    is_center_bright = center_brightness > 200

    return is_left_uniform and is_right_uniform and is_center_bright


# --- Page feature detection ---


def has_back_arrow(screenshot_bytes: bytes) -> bool:
    """
    Detect if there's a back arrow (<) in the top-left corner.
    This indicates we're in a sub-page, not the main tab screen.

    Strategy: Check the top-left region for a '<' shaped edge pattern.
    """
    img = _bytes_to_cv2(screenshot_bytes)
    h, w = img.shape[:2]

    # Top-left region where back arrow typically appears
    top_left = img[int(h * 0.02) : int(h * 0.06), int(w * 0.01) : int(w * 0.08)]
    gray = cv2.cvtColor(top_left, cv2.COLOR_BGR2GRAY)

    # Back arrow is typically dark on light background or light on dark
    # Check for significant edges in this region
    edges = cv2.Canny(gray, 50, 150)
    edge_count = np.sum(edges > 0)

    # If there are enough edges, likely has back arrow
    return edge_count > 50


def has_camera_icon_top_right(screenshot_bytes: bytes) -> bool:
    """
    Detect if there's a camera icon in the top-right corner (Moments feed).
    Album filter screen has "完成" or search: fewer total edges in that region.
    Moments feed camera icon yields a high edge count; we use total + right-share to separate.
    """
    img = _bytes_to_cv2(screenshot_bytes)
    h, w = img.shape[:2]
    crop = img[int(h * 0.01) : int(h * 0.05), int(w * 0.85) : int(w * 0.98)]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    crop_w = crop.shape[1]
    mid = int(crop_w * 0.55)
    left_edges = np.sum(edges[:, :mid] > 0)
    right_edges = np.sum(edges[:, mid:] > 0)
    total = left_edges + right_edges
    if total <= 30:
        return False
    # Moments feed: high total edges; filter screen has lower total (e.g. ~700 vs ~1160)
    if total < 800:
        return False
    # Some fixtures have more edges on the left; require at least a share on the right
    return right_edges >= 0.1 * total


def is_album_filter_screen(screenshot_bytes: bytes) -> bool:
    """
    Detect album filter/category sub-screen (e.g. 搜索照片、事物、地点, 人像/事物).
    Dark header + back arrow + no camera icon (top-right has 完成/search, not compact icon).
    Album picker is already excluded earlier in identification order (has grid + dark bar).
    """
    if detect_center_dialog(screenshot_bytes):
        return False
    if detect_bottom_sheet(screenshot_bytes):
        return False
    if has_submit_button_area(screenshot_bytes):
        return False
    if is_album_dropdown(screenshot_bytes):
        return False
    if is_album_picker(screenshot_bytes):
        return False
    if has_tab_bar(screenshot_bytes):
        return False
    if not has_back_arrow(screenshot_bytes):
        return False
    # Moments feed has compact camera icon in top-right; filter has 完成/search (edges less concentrated)
    if has_camera_icon_top_right(screenshot_bytes):
        return False

    img = _bytes_to_cv2(screenshot_bytes)
    h, w = img.shape[:2]
    header = img[int(h * 0.02) : int(h * 0.06), :]
    gray_header = cv2.cvtColor(header, cv2.COLOR_BGR2GRAY)
    if float(np.mean(gray_header)) > 100:
        return False  # Light header = not this screen

    return True


def is_moments_feed(screenshot_bytes: bytes) -> bool:
    """
    Detect if we're on the Moments feed page (without any overlay).

    Characteristics:
    - Has back arrow in top-left
    - Has camera icon in top-right (NOT green submit button)
    - No bottom tab bar
    - No bottom sheet overlay
    - No center dialog overlay
    - NOT album picker (has dark header/bottom)
    - NOT album dropdown (has dark header with album list)
    - NOT compose screen (has submit button)
    """
    # Must NOT have center dialog (dialog appears over any page)
    if detect_center_dialog(screenshot_bytes):
        return False

    # Must NOT have bottom sheet (bottom sheet appears over moments feed)
    if detect_bottom_sheet(screenshot_bytes):
        return False

    # Must NOT be album dropdown (album dropdown also has dark header)
    if is_album_dropdown(screenshot_bytes):
        return False

    # Must NOT be album picker (album picker also has back arrow and icons)
    if is_album_picker(screenshot_bytes):
        return False

    # Must NOT have submit button (compose screen has submit button)
    if has_submit_button_area(screenshot_bytes):
        return False

    # Must have back arrow (sub-page indicator)
    if not has_back_arrow(screenshot_bytes):
        return False

    # Should NOT have tab bar (we're in a sub-page)
    if has_tab_bar(screenshot_bytes):
        return False

    # Camera icon in top-right is visible when feed is at top; when scrolled it may be off-screen
    if has_camera_icon_top_right(screenshot_bytes):
        return True
    # Scrolled feed: no camera visible; accept as moments feed only if not album filter
    if is_album_filter_screen(screenshot_bytes):
        return False
    # Very bright header (e.g. > 220) with no camera often = other page (e.g. personal profile), not moments
    img = _bytes_to_cv2(screenshot_bytes)
    h, w = img.shape[:2]
    header = img[int(h * 0.02) : int(h * 0.06), int(w * 0.1) : int(w * 0.9)]
    if float(np.mean(cv2.cvtColor(header, cv2.COLOR_BGR2GRAY))) > 220:
        return False
    # Scrolled moments feed has moderate center edges (post cards); other pages (e.g. profile) can have higher
    center = img[int(h * 0.2) : int(h * 0.7), int(w * 0.2) : int(w * 0.8)]
    center_edges = cv2.Canny(cv2.cvtColor(center, cv2.COLOR_BGR2GRAY), 50, 150)
    if float(np.sum(center_edges > 0)) / center_edges.size > 0.04:
        return False
    return True


def is_compose_screen(screenshot_bytes: bytes) -> bool:
    """
    Detect if we're on the compose screen (image+text or long text).

    Key feature: Green "发表" button in the top-right corner.
    This is the most reliable indicator of the compose screen.

    Uses ratio-based thresholds for resolution independence.
    """
    img = _bytes_to_cv2(screenshot_bytes)
    h, w = img.shape[:2]

    # Check for green "发表" button in top-right (roughly 75-98% width, 2-7% height)
    top_right = img[int(h * 0.02) : int(h * 0.07), int(w * 0.75) : int(w * 0.98)]
    hsv = cv2.cvtColor(top_right, cv2.COLOR_BGR2HSV)

    # Green color range for the button
    lower_green = np.array([35, 80, 80])
    upper_green = np.array([85, 255, 255])
    mask = cv2.inRange(hsv, lower_green, upper_green)

    # Use ratio instead of absolute pixel count
    green_ratio = float(np.sum(mask > 0)) / mask.size

    # Green button should cover > 1% of the top-right region
    return green_ratio > 0.01


def has_green_submit_button(screenshot_bytes: bytes) -> bool:
    """
    Detect if there's a green submit/发表 button in the top-right.
    This is characteristic of compose screens.
    """
    return is_compose_screen(screenshot_bytes)


def has_submit_button_area(screenshot_bytes: bytes) -> bool:
    """
    Detect if there's a submit button area in the top-right (green or gray).

    This detects compose screens even when the button is disabled (gray).

    Key differentiator: Compose screens have a WHITE header bar with back arrow,
    while WeChat main has a WHITE header but with tab bar at bottom.
    Moments feed has back arrow + camera icon in top-right (not 发表).
    """
    # Moments feed has back arrow + camera icon; do not treat as compose
    if has_back_arrow(screenshot_bytes) and has_camera_icon_top_right(screenshot_bytes):
        return False

    img = _bytes_to_cv2(screenshot_bytes)
    h, w = img.shape[:2]

    # First check: must have bright header (compose screens have white header)
    header = img[int(h * 0.02) : int(h * 0.06), int(w * 0.10) : int(w * 0.90)]
    gray_header = cv2.cvtColor(header, cv2.COLOR_BGR2GRAY)
    header_brightness = float(np.mean(gray_header))

    if header_brightness < 200:
        return False  # Dark header = not compose screen

    # Second check: must NOT have tab bar (compose screens don't have tab bar)
    if has_tab_bar(screenshot_bytes):
        return False  # Has tab bar = WeChat main, not compose

    # Third check: look for green button OR gray button text
    top_right = img[int(h * 0.02) : int(h * 0.07), int(w * 0.80) : int(w * 0.98)]
    hsv = cv2.cvtColor(top_right, cv2.COLOR_BGR2HSV)

    # Check for green (active button)
    lower_green = np.array([35, 80, 80])
    upper_green = np.array([85, 255, 255])
    mask = cv2.inRange(hsv, lower_green, upper_green)

    # Use ratio instead of absolute pixel count
    green_ratio = float(np.sum(mask > 0)) / mask.size

    if green_ratio > 0.01:
        return True  # Green submit button (> 1% of region)

    # Check for gray button (inactive) - look for text edges
    gray_tr = cv2.cvtColor(top_right, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray_tr, 50, 150)
    edge_ratio = float(np.sum(edges > 0)) / edges.size

    # Scrolled moments feed / other sub-pages (e.g. personal profile) can have back arrow + bright
    # header + edges in top-right. Require higher header brightness and higher edge density so we
    # don't treat them as compose (发表 button has more concentrated edges).
    back_no_camera = has_back_arrow(screenshot_bytes) and not has_camera_icon_top_right(
        screenshot_bytes
    )
    if back_no_camera and header_brightness < 225:
        return False
    if back_no_camera and edge_ratio <= 0.04:
        return False  # e.g. personal profile ~0.036; compose gray button ~0.043+
    if edge_ratio > 0.01:
        return True

    return False


def is_album_dropdown(screenshot_bytes: bytes) -> bool:
    """
    Detect if the album dropdown menu is open.

    Characteristics:
    - Dark header bar (same as album picker)
    - Left side has small thumbnails (about 15% width)
    - A vertical divider line between thumbnails and album list
    - Right side has album list with dark background and white text

    Key differentiator from album picker:
    - Album dropdown has a uniform dark divider line (very low std < 10)
    - Album picker has image content in that region (high std > 30)
    """
    img = _bytes_to_cv2(screenshot_bytes)
    h, w = img.shape[:2]

    # First check: must have dark header (like album picker)
    header = img[int(h * 0.02) : int(h * 0.06), :]
    gray_header = cv2.cvtColor(header, cv2.COLOR_BGR2GRAY)
    header_brightness = float(np.mean(gray_header))

    if header_brightness > 100:
        return False  # Light header = not album dropdown

    # Check the divider region (14-18% from left)
    # This is where the vertical divider appears in dropdown mode
    mid_region = img[int(h * 0.15) : int(h * 0.85), :]
    divider_region = mid_region[:, int(w * 0.14) : int(w * 0.18)]
    gray_divider = cv2.cvtColor(divider_region, cv2.COLOR_BGR2GRAY)

    divider_std = float(np.std(gray_divider))

    # Album dropdown: uniform dark divider (std < 10)
    # Album picker: image content in this region (std > 30)
    return divider_std < 10


def find_wechatmcp_in_album_dropdown(screenshot_bytes: bytes) -> tuple[int, int] | None:
    """
    Find the "WeChatMCP" album entry in the dropdown list using OCR.
    Returns (x, y) center in full image coordinates, or None if not found / OCR unavailable.

    The album list is on the right side of the screen when the dropdown is open.
    WeChatMCP position changes (e.g. sorted by image count), so fixed coordinates are unreliable.
    """
    if not _PYTESSERACT_AVAILABLE:
        return None

    img = _bytes_to_cv2(screenshot_bytes)
    h, w = img.shape[:2]

    # Album list region: right side, exclude header and bottom bar
    x1 = int(w * 0.18)
    y1 = int(h * 0.12)
    x2 = int(w * 0.95)
    y2 = int(h * 0.88)
    crop = img[y1:y2, x1:x2]

    # Prefer grayscale for OCR on dark UI (white text)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    pil_img = Image.fromarray(gray)

    try:
        data = pytesseract.image_to_data(pil_img, output_type=Output.DICT, lang="eng")
    except (pytesseract.TesseractNotFoundError, Exception):
        return None

    n = len(data["text"])
    target = "WeChatMCP"
    for i in range(n):
        word = (data["text"][i] or "").strip()
        if not word:
            continue
        if target in word or word in target:
            left = data["left"][i]
            top = data["top"][i]
            width = data["width"][i]
            height = data["height"][i]
            # Center in crop, then to full image coords
            cx = x1 + left + width // 2
            cy = y1 + top + height // 2
            return (cx, cy)

    # Try matching concatenated words (e.g. "WeChat" + "MCP" in two boxes)
    combined = ""
    start_idx = None
    for i in range(n):
        word = (data["text"][i] or "").strip()
        if not word:
            if target in combined and start_idx is not None:
                break
            combined = ""
            start_idx = None
            continue
        if start_idx is None:
            start_idx = i
        combined += word
        if target in combined:
            # Use box from start_idx to i
            left = min(data["left"][k] for k in range(start_idx, i + 1))
            top = min(data["top"][k] for k in range(start_idx, i + 1))
            right = max(data["left"][k] + data["width"][k] for k in range(start_idx, i + 1))
            bottom = max(data["top"][k] + data["height"][k] for k in range(start_idx, i + 1))
            cx = x1 + (left + right) // 2
            cy = y1 + (top + bottom) // 2
            return (cx, cy)

    return None


def find_green_done_button_in_picker(screenshot_bytes: bytes) -> tuple[int, int] | None:
    """
    Find the green "完成" (Done) button in the album picker bottom bar by color, not OCR.
    When photos are selected, that button becomes a distinct green region.
    Returns (x, y) center in full image coordinates, or None if no green blob found.

    Uses the same bottom 12% / right half region; detects WeChat green via HSV mask.
    """
    img = _bytes_to_cv2(screenshot_bytes)
    h, w = img.shape[:2]

    # Bottom bar: roughly bottom 12% (预览 / 制作视频 / 完成)
    y1 = int(h * 0.88)
    y2 = h
    x1 = int(w * 0.5)
    x2 = w
    crop = img[y1:y2, x1:x2]
    crop_h, crop_w = crop.shape[:2]

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    # WeChat green (e.g. #07C160): H in [35, 85], sufficient S and V
    lower_green = np.array([35, 80, 80])
    upper_green = np.array([85, 255, 255])
    mask = cv2.inRange(hsv, lower_green, upper_green)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    # Minimum area: avoid tiny noise (button is a visible block)
    min_area = (crop_w * crop_h) * 0.02
    candidates = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        M = cv2.moments(c)
        if M["m00"] <= 0:
            continue
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        candidates.append((cx, cy, area))

    if not candidates:
        return None
    # Prefer the rightmost green blob (完成 is on the right of the bar)
    candidates.sort(key=lambda t: (-t[0], -t[2]))
    cx_rel, cy_rel, _ = candidates[0]
    return (x1 + cx_rel, y1 + cy_rel)


def find_album_done_in_picker(screenshot_bytes: bytes) -> tuple[int, int] | None:
    """
    Find the "完成" (Done) button in the album picker bottom bar.
    Prefers green-region detection (OpenCV); falls back to OCR if no green blob found.

    Returns (x, y) center in full image coordinates, or None if not found.
    """
    coords = find_green_done_button_in_picker(screenshot_bytes)
    if coords is not None:
        return coords

    if not _PYTESSERACT_AVAILABLE:
        return None

    img = _bytes_to_cv2(screenshot_bytes)
    h, w = img.shape[:2]
    y1 = int(h * 0.88)
    y2 = h
    x1 = int(w * 0.5)
    x2 = w
    crop = img[y1:y2, x1:x2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    pil_img = Image.fromarray(gray)

    try:
        data = pytesseract.image_to_data(pil_img, output_type=Output.DICT, lang="chi_sim+eng")
    except (pytesseract.TesseractNotFoundError, pytesseract.TesseractError, Exception):
        return None

    n = len(data["text"])
    target = "完成"
    for i in range(n):
        word = (data["text"][i] or "").strip()
        if not word:
            continue
        if target in word or word == target:
            left = data["left"][i]
            top = data["top"][i]
            width = data["width"][i]
            height = data["height"][i]
            cx = x1 + left + width // 2
            cy = y1 + top + height // 2
            return (cx, cy)

    return None


def extract_moments_feed_top_text(screenshot_bytes: bytes) -> str:
    """
    Extract text from the top post in Moments feed using OCR.
    This is used to verify that a newly published post actually appears at the top.

    Returns the extracted text, or empty string if OCR unavailable or no text found.

    Strategy: Extract text from the top post content area (below header, above second post).
    The area roughly spans 8%-40% height and 10%-95% width (avoiding left-side profile pics).
    """
    if not _PYTESSERACT_AVAILABLE:
        return ""

    img = _bytes_to_cv2(screenshot_bytes)
    h, w = img.shape[:2]

    # Top post content region: below cover photo (~18%) to mid-screen (55%)
    # The cover photo / header occupies roughly the top 15-18% on most devices.
    # Avoid left margin (profile pics are ~0-10% width)
    y1 = int(h * 0.18)
    y2 = int(h * 0.55)
    x1 = int(w * 0.05)
    x2 = int(w * 0.95)
    crop = img[y1:y2, x1:x2]

    # Convert to grayscale for better OCR
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    pil_img = Image.fromarray(gray)

    try:
        # Use both Chinese and English for text extraction
        text = pytesseract.image_to_string(pil_img, lang="chi_sim+eng")
        # Clean up: remove extra whitespace and newlines
        return " ".join(text.split())
    except (pytesseract.TesseractNotFoundError, pytesseract.TesseractError, Exception):
        return ""


def is_album_picker(screenshot_bytes: bytes) -> bool:
    """
    Detect if we're on the album/gallery picker screen (not dropdown).

    Characteristics:
    - Dark header bar and dark bottom bar
    - Grid has selection circle indicators (green checkmarks or empty circles) and/or varied content
    - No OCR (works in any system language)
    - NOT album dropdown (no uniform divider), NOT tab bar
    """
    img = _bytes_to_cv2(screenshot_bytes)
    h, w = img.shape[:2]

    # Key feature 1: Dark header bar
    header = img[int(h * 0.02) : int(h * 0.06), :]
    gray_header = cv2.cvtColor(header, cv2.COLOR_BGR2GRAY)
    if float(np.mean(gray_header)) > 100:
        return False

    # Key feature 2: Dark bottom bar (预览 / 制作视频 / 完成)
    bottom = img[int(h * 0.92) : int(h * 0.99), :]
    gray_bottom = cv2.cvtColor(bottom, cv2.COLOR_BGR2GRAY)
    if float(np.mean(gray_bottom)) > 100:
        return False

    # Content: grid variance OR selection circles (no OCR; works in any locale)
    grid_region = img[int(h * 0.10) : int(h * 0.90), :]
    gray_grid = cv2.cvtColor(grid_region, cv2.COLOR_BGR2GRAY)
    grid_std = float(np.std(gray_grid))
    has_grid_content = grid_std >= 18
    has_circles = has_selection_circles_in_album_grid(screenshot_bytes)
    if not (has_grid_content or has_circles):
        return False

    if has_tab_bar(screenshot_bytes):
        return False

    # NOT album dropdown (uniform divider at 14-18% width)
    mid_region = img[int(h * 0.15) : int(h * 0.85), :]
    divider_region = mid_region[:, int(w * 0.14) : int(w * 0.18)]
    gray_divider = cv2.cvtColor(divider_region, cv2.COLOR_BGR2GRAY)
    if float(np.std(gray_divider)) < 10:
        return False

    return True
