"""Unit tests for MCP server tools."""

import base64
import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP
from PIL import Image

from wechat_moments.server import mcp


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    """Create a sample image for testing."""
    img = Image.new("RGB", (200, 200), color=(100, 150, 200))
    p = tmp_path / "test.jpg"
    img.save(str(p))
    return p


async def _call_tool(server: FastMCP, name: str, arguments: dict) -> dict:
    """Helper to call a tool and parse JSON result."""
    from mcp.types import TextContent

    result = await server.call_tool(name, arguments)
    for content in result:
        if isinstance(content, TextContent):
            return json.loads(content.text)
    raise ValueError("No text content in result")


# ═══════════════════════════════════════════════════════════════════════════════
# Tool Registration Tests
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_tools_registered():
    """Verify all expected tools are registered."""
    tools = await mcp.list_tools()
    tool_names = [t.name for t in tools]

    assert "prepare_post" in tool_names
    assert "submit_post" in tool_names
    assert "get_submit_status" in tool_names
    assert "get_device_status" in tool_names
    assert "take_screenshot" in tool_names
    assert "get_image" in tool_names


# ═══════════════════════════════════════════════════════════════════════════════
# prepare_post Tests
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_prepare_post_text_only(tmp_path, monkeypatch):
    """Test prepare_post with text only."""
    monkeypatch.setattr("wechat_moments.preview.STAGING_DIR", tmp_path / "staging")

    data = await _call_tool(mcp, "prepare_post", {"text": "测试文案"})

    assert "post_id" in data
    assert "preview_path" in data
    assert "preview_resource_uri" in data
    assert data["preview_resource_uri"].startswith("resource://preview/")


@pytest.mark.asyncio
async def test_prepare_post_with_embed_preview(tmp_path, monkeypatch):
    """Test prepare_post with embed_preview option."""
    monkeypatch.setattr("wechat_moments.preview.STAGING_DIR", tmp_path / "staging")

    data = await _call_tool(
        mcp,
        "prepare_post",
        {
            "text": "测试",
            "options": {"embed_preview": True},
        },
    )

    assert "preview_base64" in data
    assert "preview_mime_type" in data
    assert data["preview_mime_type"] == "image/jpeg"
    # Verify base64 is valid
    decoded = base64.b64decode(data["preview_base64"])
    assert len(decoded) > 0


@pytest.mark.asyncio
async def test_prepare_post_without_embed_preview(tmp_path, monkeypatch):
    """Test prepare_post without embed_preview (default)."""
    monkeypatch.setattr("wechat_moments.preview.STAGING_DIR", tmp_path / "staging")

    data = await _call_tool(mcp, "prepare_post", {"text": "测试"})

    assert "preview_base64" not in data
    assert "preview_resource_uri" in data


@pytest.mark.asyncio
async def test_prepare_post_with_local_image(tmp_path, sample_image, monkeypatch):
    """Test prepare_post with local file path."""
    monkeypatch.setattr("wechat_moments.preview.STAGING_DIR", tmp_path / "staging")

    data = await _call_tool(
        mcp,
        "prepare_post",
        {
            "text": "配图测试",
            "images": [str(sample_image)],
        },
    )

    assert "staged_images" in data
    assert len(data["staged_images"]) == 1


@pytest.mark.asyncio
async def test_prepare_post_with_file_uri(tmp_path, sample_image, monkeypatch):
    """Test prepare_post with file:// URI."""
    monkeypatch.setattr("wechat_moments.preview.STAGING_DIR", tmp_path / "staging")

    data = await _call_tool(
        mcp,
        "prepare_post",
        {
            "text": "file URI 测试",
            "images": [f"file://{sample_image}"],
        },
    )

    assert len(data["staged_images"]) == 1


@pytest.mark.asyncio
async def test_prepare_post_with_data_uri(tmp_path, sample_image, monkeypatch):
    """Test prepare_post with data URI."""
    monkeypatch.setattr("wechat_moments.preview.STAGING_DIR", tmp_path / "staging")

    # Create data URI from sample image
    img_bytes = sample_image.read_bytes()
    data_uri = f"data:image/jpeg;base64,{base64.b64encode(img_bytes).decode()}"

    data = await _call_tool(
        mcp,
        "prepare_post",
        {
            "text": "data URI 测试",
            "images": [data_uri],
        },
    )

    assert len(data["staged_images"]) == 1


from mcp.server.fastmcp.exceptions import ToolError


@pytest.mark.asyncio
async def test_prepare_post_empty_raises_error(tmp_path, monkeypatch):
    """Test prepare_post with no text and no images raises error."""
    monkeypatch.setattr("wechat_moments.preview.STAGING_DIR", tmp_path / "staging")

    with pytest.raises(ToolError):
        await _call_tool(mcp, "prepare_post", {})


# ═══════════════════════════════════════════════════════════════════════════════
# get_image Tests
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_image_success(sample_image):
    """Test get_image with valid image path."""
    data = await _call_tool(mcp, "get_image", {"path": str(sample_image)})

    assert "base64" in data
    assert data["mime_type"] == "image/jpeg"
    assert data["size_bytes"] > 0


@pytest.mark.asyncio
async def test_get_image_not_found():
    """Test get_image with non-existent path."""
    data = await _call_tool(mcp, "get_image", {"path": "/nonexistent/image.jpg"})

    assert "error" in data
    assert "not found" in data["error"].lower()


@pytest.mark.asyncio
async def test_get_image_not_image_file(tmp_path):
    """Test get_image with non-image file."""
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("not an image")

    data = await _call_tool(mcp, "get_image", {"path": str(txt_file)})

    assert "error" in data


# ═══════════════════════════════════════════════════════════════════════════════
# get_device_status Tests
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_device_status_no_device(mocker):
    """Test get_device_status when no device connected."""
    mocker.patch("wechat_moments.server.ADB.get_connected_serials", return_value=[])

    data = await _call_tool(mcp, "get_device_status", {})

    assert data["connected"] is False
    assert "error" in data


# ═══════════════════════════════════════════════════════════════════════════════
# submit_post / get_submit_status Tests
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_submit_post_returns_job_id(tmp_path, monkeypatch, mocker):
    """Test submit_post returns job_id immediately."""
    monkeypatch.setattr("wechat_moments.preview.STAGING_DIR", tmp_path / "staging")

    # Mock execute_submit to avoid actual ADB operations
    mocker.patch("wechat_moments.server.execute_submit", return_value={"status": "success"})

    # First prepare a post
    prep_data = await _call_tool(mcp, "prepare_post", {"text": "测试"})
    post_id = prep_data["post_id"]

    # Submit
    submit_data = await _call_tool(mcp, "submit_post", {"post_id": post_id})

    assert "job_id" in submit_data
    assert submit_data["status"] == "running"


@pytest.mark.asyncio
async def test_get_submit_status_not_found():
    """Test get_submit_status with invalid job_id."""
    data = await _call_tool(mcp, "get_submit_status", {"job_id": "nonexistent"})

    assert data["status"] == "not_found"


# ═══════════════════════════════════════════════════════════════════════════════
# MCP Resource Tests
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_preview_resource_registered():
    """Verify preview resource template is registered."""
    resources = await mcp.list_resource_templates()
    uris = [r.uriTemplate for r in resources]
    assert "resource://preview/{post_id}" in uris


@pytest.mark.asyncio
async def test_preview_resource_returns_bytes(tmp_path, monkeypatch):
    """Test that preview resource returns image bytes."""
    staging_dir = tmp_path / "staging"
    monkeypatch.setattr("wechat_moments.preview.STAGING_DIR", staging_dir)
    monkeypatch.setattr("wechat_moments.server.STAGING_DIR", staging_dir)

    # Prepare a post to create preview
    prep_data = await _call_tool(mcp, "prepare_post", {"text": "Resource test"})
    post_id = prep_data["post_id"]

    # Read the resource
    from mcp.types import AnyUrl

    result = await mcp.read_resource(AnyUrl(f"resource://preview/{post_id}"))

    assert len(result) > 0
    # Resource returns ReadResourceContents with content attribute containing bytes
    content = result[0]
    assert hasattr(content, "content")
    # Verify it's JPEG data (starts with FFD8)
    assert content.content[:2] == b"\xff\xd8"
