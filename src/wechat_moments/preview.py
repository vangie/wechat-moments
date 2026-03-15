"""
Staging directory management, preview image generation, and post lifecycle.
"""

import base64 as b64
import json
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict

import httpx
from PIL import Image, ImageDraw, ImageFont

from .config import (
    ARCHIVE_DIR,
    ARCHIVE_EXPIRE_DAYS,
    STAGING_DIR,
    STAGING_EXPIRE_HOURS,
    WECHAT_DISPLAY_NAME,
)


class PostMeta(TypedDict):
    post_id: str
    text: str
    image_count: int
    created_at: str
    expires_at: str
    status: str  # prepared | submitting | submitted


class PreparedPost(TypedDict):
    post_id: str
    preview_path: str
    staged_images: list[str]
    expires_at: str


def _new_post_id() -> str:
    return uuid.uuid4().hex[:8]


def _staging_path(post_id: str) -> Path:
    return STAGING_DIR / post_id


def _archive_path(post_id: str) -> Path:
    return ARCHIVE_DIR / post_id


def _read_meta(post_id: str) -> PostMeta:
    path = _staging_path(post_id) / "meta.json"
    if not path.exists():
        # Also check archive (already submitted)
        path = _archive_path(post_id) / "meta.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _write_meta(post_id: str, meta: PostMeta) -> None:
    (_staging_path(post_id) / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def update_meta_status(post_id: str, status: str, **extra: str) -> None:
    meta = _read_meta(post_id)
    meta["status"] = status
    meta.update(extra)  # type: ignore[arg-type]
    _write_meta(post_id, meta)


def _download_image(url: str, dest: Path) -> None:
    with httpx.Client(follow_redirects=True, timeout=30) as client:
        response = client.get(url)
        response.raise_for_status()
        dest.write_bytes(response.content)


def _decode_data_uri(data_uri: str, dest: Path) -> None:
    """Decode data URI and save to file."""
    # data:image/jpeg;base64,/9j/4AAQ...
    if not data_uri.startswith("data:"):
        raise ValueError("Invalid data URI")
    header, encoded = data_uri.split(",", 1)
    data = b64.b64decode(encoded)
    dest.write_bytes(data)


def _stage_image(source: str, dest: Path) -> None:
    """Copy or download an image to the staging directory."""
    if source.startswith("data:"):
        _decode_data_uri(source, dest)
    elif source.startswith("http://") or source.startswith("https://"):
        _download_image(source, dest)
    elif source.startswith("file://"):
        # file:///Users/vangie/photo.jpg → /Users/vangie/photo.jpg
        local_path = source[7:]  # strip "file://"
        shutil.copy2(local_path, dest)
    else:
        # Local path shorthand
        shutil.copy2(source, dest)


def _load_chinese_font(size: int) -> "ImageFont.FreeTypeFont":
    """Load a CJK-capable font, trying multiple system paths."""
    candidates = [
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size, index=0)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _wrap_text(text: str, font: "ImageFont.FreeTypeFont", max_width: int) -> list[str]:
    """Wrap text to fit within max_width using actual font metrics."""
    lines: list[str] = []
    current = ""
    for ch in text:
        if ch == "\n":
            lines.append(current)
            current = ""
            continue
        test = current + ch
        try:
            w = font.getlength(test)
        except AttributeError:
            w = len(test) * (font.size if hasattr(font, "size") else 12)
        if w > max_width and current:
            lines.append(current)
            current = ch
        else:
            current = test
    if current:
        lines.append(current)
    return lines or [""]


def _build_preview_image(text: str, image_paths: list[Path], output: Path) -> None:
    """
    Compose a WeChat Moments-style preview card pixel-matched to the real app.

    Structure
    ---------
    ┌─────────────────────────── 1080px ──────────────────────────────┐
    │ ░ 朋友圈 ░ ░ ░  (100px header, white bg)                        │
    ├─────────────────────────────────────────────────────────────────┤
    │ [avatar 76×76] username (WeChat blue)                           │
    │               post text                                         │
    │               image grid                                        │
    │               刚刚                                              │
    └─────────────────────────────────────────────────────────────────┘
    """
    # ── Palette ───────────────────────────────────────────────────────────────
    PAGE_BG = (237, 237, 237)  # #EDEDED outer background
    CARD_BG = (255, 255, 255)  # white card
    DIVIDER = (229, 229, 229)  # #E5E5E5
    USERNAME_CLR = (87, 107, 149)  # #576b95 WeChat blue
    TEXT_CLR = (51, 51, 51)  # #333333
    TIME_CLR = (138, 138, 138)  # #8a8a8a
    AVATAR_BDR = (218, 218, 218)  # avatar border

    # ── Metrics (derived from 1080-px phone screenshots) ──────────────────────
    W = 1080
    HEADER_H = 100
    LEFT_PAD = 24
    TOP_PAD = 20
    AVATAR_SIZE = 76
    AVT_GAP = 12
    CONTENT_X = LEFT_PAD + AVATAR_SIZE + AVT_GAP  # 112
    CONTENT_W = W - CONTENT_X - LEFT_PAD  # 944
    GRID_GAP = 8
    SINGLE_MAX = 630  # single image: max width keeps left whitespace

    HEADER_SZ = 38
    USERNAME_SZ = 30
    TEXT_SZ = 28
    TIME_SZ = 24
    LINE_H = TEXT_SZ + 10

    header_font = _load_chinese_font(HEADER_SZ)
    username_font = _load_chinese_font(USERNAME_SZ)
    text_font = _load_chinese_font(TEXT_SZ)
    time_font = _load_chinese_font(TIME_SZ)

    # ── Text ──────────────────────────────────────────────────────────────────
    text_lines = _wrap_text(text, text_font, CONTENT_W) if text else []

    # ── Thumbnail images (square-cropped) ─────────────────────────────────────
    thumb_imgs: list[Image.Image] = []
    if image_paths:
        n = len(image_paths)
        cell_w = (
            min(CONTENT_W, SINGLE_MAX)
            if n == 1
            else (CONTENT_W - (n - 1) * GRID_GAP) // n
            if n <= 3
            else (CONTENT_W - 2 * GRID_GAP) // 3
        )
        for p in image_paths:
            try:
                img = Image.open(p).convert("RGB")
            except Exception:
                img = Image.new("RGB", (cell_w, cell_w), (200, 200, 200))
            side = min(img.size)
            x0 = (img.width - side) // 2
            y0 = (img.height - side) // 2
            img = img.crop((x0, y0, x0 + side, y0 + side)).resize((cell_w, cell_w), Image.LANCZOS)
            thumb_imgs.append(img)

    # ── Canvas height ─────────────────────────────────────────────────────────
    username_h = USERNAME_SZ + 10
    text_h = len(text_lines) * LINE_H + (8 if text_lines else 0)

    grid_h = 0
    if thumb_imgs:
        n = len(thumb_imgs)
        rows = 1 if n <= 3 else (n + 2) // 3
        cw_h = (
            min(CONTENT_W, SINGLE_MAX)
            if n == 1
            else (CONTENT_W - (n - 1) * GRID_GAP) // n
            if n <= 3
            else (CONTENT_W - 2 * GRID_GAP) // 3
        )
        grid_h = rows * cw_h + (rows - 1) * GRID_GAP + 16

    time_h = TIME_SZ + 16
    card_h = TOP_PAD + max(AVATAR_SIZE, username_h + text_h + grid_h + time_h) + TOP_PAD
    total_h = HEADER_H + 1 + card_h

    # ── Draw ──────────────────────────────────────────────────────────────────
    canvas = Image.new("RGB", (W, total_h), PAGE_BG)
    draw = ImageDraw.Draw(canvas)

    # Header bar
    draw.rectangle([0, 0, W - 1, HEADER_H - 1], fill=CARD_BG)
    try:
        hw = header_font.getlength("朋友圈")
    except AttributeError:
        hw = HEADER_SZ * 3
    draw.text(
        ((W - hw) // 2, (HEADER_H - HEADER_SZ) // 2), "朋友圈", fill=(0, 0, 0), font=header_font
    )
    draw.line([(0, HEADER_H), (W, HEADER_H)], fill=DIVIDER, width=1)

    # Card
    draw.rectangle([0, HEADER_H + 1, W - 1, total_h - 1], fill=CARD_BG)

    # Avatar (grey placeholder; user profile photo is not available at preview time)
    ay = HEADER_H + 1 + TOP_PAD
    draw.rectangle(
        [LEFT_PAD, ay, LEFT_PAD + AVATAR_SIZE, ay + AVATAR_SIZE],
        fill=(180, 180, 180),
    )
    draw.rectangle(
        [LEFT_PAD, ay, LEFT_PAD + AVATAR_SIZE - 1, ay + AVATAR_SIZE - 1],
        outline=AVATAR_BDR,
        width=1,
    )

    # Username
    cy = ay
    draw.text((CONTENT_X, cy), WECHAT_DISPLAY_NAME, fill=USERNAME_CLR, font=username_font)
    cy += username_h

    # Text
    for line in text_lines:
        draw.text((CONTENT_X, cy), line, fill=TEXT_CLR, font=text_font)
        cy += LINE_H
    if text_lines:
        cy += 8

    # Image grid
    if thumb_imgs:
        n = len(thumb_imgs)
        cw_r = (
            min(CONTENT_W, SINGLE_MAX)
            if n == 1
            else (CONTENT_W - (n - 1) * GRID_GAP) // n
            if n <= 3
            else (CONTENT_W - 2 * GRID_GAP) // 3
        )
        for idx, thumb in enumerate(thumb_imgs):
            col, row = (idx, 0) if n <= 3 else divmod(idx, 3)
            gx = CONTENT_X + col * (cw_r + GRID_GAP)
            gy = cy + row * (cw_r + GRID_GAP)
            canvas.paste(thumb.resize((cw_r, cw_r), Image.LANCZOS), (gx, gy))
        rows = 1 if n <= 3 else (n + 2) // 3
        cy += rows * cw_r + (rows - 1) * GRID_GAP + 16

    # Timestamp
    draw.text((CONTENT_X, cy), "刚刚", fill=TIME_CLR, font=time_font)

    # Bottom divider
    draw.line([(0, total_h - 1), (W, total_h - 1)], fill=DIVIDER, width=1)

    canvas.save(str(output), "JPEG", quality=92)


def prepare_post(text: str, images: list[str]) -> PreparedPost:
    """
    Stage images (download if URLs), generate preview, return PreparedPost.
    Raises ValueError if neither text nor images are provided.
    """
    if not text and not images:
        raise ValueError("At least one of text or images must be provided")

    post_id = _new_post_id()
    staging = _staging_path(post_id)
    staging.mkdir(parents=True, exist_ok=True)

    now = datetime.now(tz=UTC)
    expires_at = (now + timedelta(hours=STAGING_EXPIRE_HOURS)).isoformat()

    # Stage images
    staged_paths: list[Path] = []
    for i, src in enumerate(images):
        # Determine file extension
        if src.startswith("data:"):
            # Extract MIME type from data URI: data:image/jpeg;base64,...
            mime_part = src.split(";")[0]  # "data:image/jpeg"
            mime_type = mime_part.split(":")[1] if ":" in mime_part else "image/jpeg"
            ext_map = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/gif": ".gif",
                "image/webp": ".webp",
            }
            suffix = ext_map.get(mime_type, ".jpg")
        elif src.startswith("http"):
            suffix = ".jpg"
        else:
            suffix = Path(src).suffix or ".jpg"
        dest = staging / f"IMG_{i + 1:04d}{suffix}"
        _stage_image(src, dest)
        staged_paths.append(dest)

    # Generate preview
    preview_path = staging / "preview.jpg"
    _build_preview_image(text, staged_paths, preview_path)

    # Write meta
    meta: PostMeta = {
        "post_id": post_id,
        "text": text,
        "image_count": len(staged_paths),
        "created_at": now.isoformat(),
        "expires_at": expires_at,
        "status": "prepared",
    }
    _write_meta(post_id, meta)

    return PreparedPost(
        post_id=post_id,
        preview_path=str(preview_path),
        staged_images=[str(p) for p in staged_paths],
        expires_at=expires_at,
    )


def get_staged_images(post_id: str) -> list[Path]:
    staging = _staging_path(post_id)
    return sorted(staging.glob("IMG_*.jpg")) + sorted(staging.glob("IMG_*.png"))


def get_post_text(post_id: str) -> str:
    return _read_meta(post_id)["text"]


def archive_post(post_id: str) -> str:
    """Move staging dir to archive, keeping only meta.json and preview.jpg."""
    staging = _staging_path(post_id)
    archive = _archive_path(post_id)
    archive.parent.mkdir(parents=True, exist_ok=True)

    # Update submitted_at in meta
    meta = _read_meta(post_id)
    meta["submitted_at"] = datetime.now(tz=UTC).isoformat()  # type: ignore[typeddict-unknown-key]
    meta["status"] = "submitted"
    _write_meta(post_id, meta)

    # Move only meta + preview to archive
    archive.mkdir(parents=True, exist_ok=True)
    for fname in ("meta.json", "preview.jpg"):
        src = staging / fname
        if src.exists():
            shutil.copy2(src, archive / fname)

    # Remove staging dir entirely
    shutil.rmtree(staging, ignore_errors=True)
    return str(archive)


def cleanup_expired_staging() -> int:
    """Remove staging dirs older than STAGING_EXPIRE_HOURS. Returns count removed."""
    if not STAGING_DIR.exists():
        return 0
    now = datetime.now(tz=UTC)
    removed = 0
    for d in STAGING_DIR.iterdir():
        if not d.is_dir():
            continue
        meta_file = d / "meta.json"
        if not meta_file.exists():
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            expires = datetime.fromisoformat(meta["expires_at"])
            if now > expires:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        except Exception:
            pass
    return removed


def cleanup_expired_archive() -> int:
    """Remove archive dirs older than ARCHIVE_EXPIRE_DAYS. Returns count removed."""
    if not ARCHIVE_DIR.exists():
        return 0
    now = datetime.now(tz=UTC)
    removed = 0
    for d in ARCHIVE_DIR.iterdir():
        if not d.is_dir():
            continue
        meta_file = d / "meta.json"
        if not meta_file.exists():
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            submitted = datetime.fromisoformat(meta.get("submitted_at", meta["created_at"]))
            if (now - submitted).days > ARCHIVE_EXPIRE_DAYS:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        except Exception:
            pass
    return removed
