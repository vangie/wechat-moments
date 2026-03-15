"""Unit tests for preview.py — no phone required."""

import json
from pathlib import Path

import pytest
from PIL import Image

from wechat_moments.preview import (
    _build_preview_image,
    cleanup_expired_staging,
    prepare_post,
)


@pytest.fixture()
def sample_image(tmp_path: Path) -> Path:
    img = Image.new("RGB", (200, 200), color=(100, 150, 200))
    p = tmp_path / "test.jpg"
    img.save(str(p))
    return p


def test_build_preview_text_only(tmp_path: Path) -> None:
    out = tmp_path / "preview.jpg"
    _build_preview_image("Hello 世界", [], out)
    assert out.exists()
    img = Image.open(out)
    assert img.width == 1080
    assert img.height > 0


def test_build_preview_with_images(tmp_path: Path, sample_image: Path) -> None:
    out = tmp_path / "preview.jpg"
    _build_preview_image("Test post", [sample_image, sample_image], out)
    assert out.exists()
    img = Image.open(out)
    assert img.width == 1080


def test_prepare_post_creates_staging(
    tmp_path: Path, sample_image: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("wechat_moments.preview.STAGING_DIR", tmp_path / "staging")
    monkeypatch.setattr("wechat_moments.preview.ARCHIVE_DIR", tmp_path / "archive")

    result = prepare_post("Test text", [str(sample_image)])

    post_id = result["post_id"]
    staging = tmp_path / "staging" / post_id
    assert staging.exists()
    assert (staging / "meta.json").exists()
    assert (staging / "preview.jpg").exists()
    assert len(result["staged_images"]) == 1

    meta = json.loads((staging / "meta.json").read_text())
    assert meta["status"] == "prepared"
    assert meta["text"] == "Test text"
    assert meta["image_count"] == 1


def test_prepare_post_raises_without_content() -> None:
    with pytest.raises(ValueError, match="At least one"):
        prepare_post("", [])


def test_cleanup_expired_staging_removes_old(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("wechat_moments.preview.STAGING_DIR", tmp_path)
    monkeypatch.setattr("wechat_moments.preview.ARCHIVE_DIR", tmp_path / "_archive")

    # Create an expired staging dir
    expired_dir = tmp_path / "expired123"
    expired_dir.mkdir()
    meta = {
        "post_id": "expired123",
        "text": "old",
        "image_count": 0,
        "created_at": "2020-01-01T00:00:00+00:00",
        "expires_at": "2020-01-01T01:00:00+00:00",
        "status": "prepared",
    }
    (expired_dir / "meta.json").write_text(json.dumps(meta))

    removed = cleanup_expired_staging()
    assert removed == 1
    assert not expired_dir.exists()
