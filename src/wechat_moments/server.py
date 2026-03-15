"""
MCP Server exposing tools for OpenClaw integration.
"""

import base64
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .adb import ADB
from .config import DEBUG_BASE_DIR, STAGING_DIR
from .history import log_prepare_post
from .preview import prepare_post as _prepare_post
from .submit import execute_submit


class PrepareOptions(TypedDict, total=False):
    """Options for prepare_post tool."""

    embed_preview: bool  # If True, include base64 preview in response (consumes tokens)


mcp = FastMCP(
    "wechat-moments",
    instructions=(
        "Tools for posting to WeChat Moments via ADB-connected Android phone. "
        "Typical workflow: call prepare_post() to stage content and get a preview image, "
        "optionally show the preview to the user for confirmation, "
        "then call submit_post(post_id) to start publishing (returns job_id), "
        "and poll get_submit_status(job_id) until status is 'done' or 'error'."
    ),
    # Disable DNS rebinding protection to allow remote access
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

# In-memory job store for async submit operations
_jobs: dict[str, dict[str, Any]] = {}


def _make_step_callback(job_id: str) -> Callable[[int, str, str], None]:
    """Create a callback that updates job progress on each FSM step."""

    def callback(step: int, state: str, action: str) -> None:
        job = _jobs.get(job_id)
        if job:
            if "steps" not in job:
                job["steps"] = []
            job["steps"].append(
                {
                    "step": step,
                    "state": state,
                    "action": action,
                    "timestamp": time.time(),
                }
            )
            job["current_step"] = step
            job["current_state"] = state

    return callback


@mcp.tool()
def prepare_post(
    text: str = "",
    images: list[str] | None = None,
    options: PrepareOptions | None = None,
) -> dict:
    """
    Prepare a WeChat Moments post. Downloads images from URLs if needed, stages all
    assets, and generates a preview image showing the final layout (text + image grid,
    mimicking WeChat Moments appearance). Returns a post_id and the local path to the
    preview image. Call submit_post(post_id) when ready to publish.

    At least one of text or images must be provided.

    images: List of image sources. Supported formats:
      - HTTP/HTTPS URL: "https://example.com/photo.jpg"
      - file:// URI: "file:///Users/vangie/photo.jpg"
      - Local path: "/Users/vangie/photo.jpg"
      - data URI: "data:image/jpeg;base64,/9j/4AAQ..."

    options:
      - embed_preview: If True, include base64-encoded preview image in response.
                       Warning: adds ~50-200KB, consuming tokens. Default False.
    """
    imgs = images or []
    opts = options or {}
    result = _prepare_post(text=text, images=imgs)
    log_prepare_post(result["post_id"], len(text), len(imgs))

    # Always return resource URI
    result["preview_resource_uri"] = f"resource://preview/{result['post_id']}"

    # Optionally embed base64
    if opts.get("embed_preview"):
        preview_bytes = Path(result["preview_path"]).read_bytes()
        result["preview_base64"] = base64.b64encode(preview_bytes).decode()
        result["preview_mime_type"] = "image/jpeg"

    return result


@mcp.tool()
def submit_post(post_id: str, debug: bool = False) -> dict:
    """
    Start publishing a prepared post to WeChat Moments asynchronously.

    This tool returns immediately with a job_id. Poll get_submit_status(job_id)
    every 5-10 seconds to check progress. The FSM automation may take 1-3 minutes.

    Args:
        post_id: The post ID from prepare_post
        debug: If True, save debug screenshots to DEBUG_DIR for troubleshooting

    Returns: {"job_id": str, "status": "running", "hint": str, "debug_dir"?: str}
    """
    job_id = uuid.uuid4().hex[:8]

    # Create debug directory if debug mode is enabled
    debug_dir = None
    if debug:
        from datetime import datetime

        debug_dir = DEBUG_BASE_DIR / datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        debug_dir.mkdir(parents=True, exist_ok=True)

    _jobs[job_id] = {
        "status": "running",
        "post_id": post_id,
        "started_at": time.time(),
        "steps": [],
        "debug_dir": str(debug_dir) if debug_dir else None,
    }

    step_callback = _make_step_callback(job_id)

    def _run() -> None:
        try:
            result = execute_submit(post_id, debug_dir=debug_dir, step_callback=step_callback)
            _jobs[job_id].update(
                {
                    "status": "done",
                    "result": result,
                    "finished_at": time.time(),
                }
            )
        except Exception as exc:
            _jobs[job_id].update(
                {
                    "status": "error",
                    "error": str(exc),
                    "finished_at": time.time(),
                }
            )

    threading.Thread(target=_run, daemon=True).start()
    response = {
        "job_id": job_id,
        "status": "running",
        "hint": "Poll get_submit_status(job_id) every 5-10 seconds until status is 'done' or 'error'",
    }
    if debug_dir:
        response["debug_dir"] = str(debug_dir)
    return response


@mcp.tool()
def get_submit_status(job_id: str) -> dict:
    """
    Poll the status of an async submit_post job.

    Returns:
      - status: 'running' | 'done' | 'error' | 'not_found'
      - current_step: (when running) current FSM step number
      - current_state: (when running) current FSM state name
      - steps: (when running) list of recent steps [{step, state, action}, ...]
      - result: (when done) the original submit result dict
      - error: (when error) error message string
      - elapsed_seconds: how long the job has been running
    """
    job = _jobs.get(job_id)
    if not job:
        return {"status": "not_found", "job_id": job_id}

    elapsed = time.time() - job["started_at"]
    response: dict[str, Any] = {
        "job_id": job_id,
        "status": job["status"],
        "elapsed_seconds": round(elapsed, 1),
    }

    if job["status"] == "running":
        response["current_step"] = job.get("current_step")
        response["current_state"] = job.get("current_state")
        # Return last 5 steps to keep response size reasonable
        steps = job.get("steps", [])
        response["recent_steps"] = steps[-5:] if steps else []
        response["total_steps"] = len(steps)
    elif job["status"] == "done":
        response["result"] = job.get("result")
        response["total_steps"] = len(job.get("steps", []))
    elif job["status"] == "error":
        response["error"] = job.get("error")
        response["total_steps"] = len(job.get("steps", []))

    return response


@mcp.tool()
def get_device_status() -> dict:
    """
    Check ADB connection status and whether WeChat and ADBKeyboard are installed
    on the connected Android device.
    """
    serials = ADB.get_connected_serials()
    if not serials:
        return {"connected": False, "error": "No ADB devices found"}

    serial = serials[0]
    adb = ADB(serial=serial)
    return {
        "connected": True,
        "serial": serial,
        "wechat_installed": adb.is_app_installed("com.tencent.mm"),
        "adbkeyboard_installed": adb.is_app_installed("com.android.adbkeyboard"),
    }


@mcp.tool()
def take_screenshot() -> dict:
    """
    Take a screenshot of the current phone screen. Returns local path to the PNG file.
    Wakes and unlocks the screen first so the screenshot is not black.
    Useful for debugging FSM state or verifying the current WeChat UI.
    """
    adb = ADB.auto_connect()
    adb.wake_screen()
    with tempfile.NamedTemporaryFile(
        suffix=".png",
        delete=False,
        dir=str(Path.home() / ".local/share/wechat-moments"),
        prefix="screenshot_",
    ) as f:
        path = f.name
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    adb.screenshot_to_file(path)
    return {"screenshot_path": path}


@mcp.resource("resource://preview/{post_id}")
def get_preview_resource(post_id: str) -> bytes:
    """Preview image for a prepared post."""
    preview_path = STAGING_DIR / post_id / "preview.jpg"
    if not preview_path.exists():
        raise FileNotFoundError(f"Preview not found for {post_id}")
    return preview_path.read_bytes()


@mcp.tool()
def get_image(path: str) -> dict:
    """
    Read an image file and return as base64.

    Use for inspecting:
    - Preview images (preview_path from prepare_post)
    - Staged images (staged_images from prepare_post)
    - Screenshots (screenshot_path from take_screenshot)

    Warning: Consumes tokens proportional to image size (~50-200KB per image).

    path: Absolute path to image file
    """
    p = Path(path)
    if not p.exists():
        return {"error": f"File not found: {path}"}
    if p.suffix.lower() not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        return {"error": f"Not an image file: {path}"}

    data = p.read_bytes()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    return {
        "path": path,
        "base64": base64.b64encode(data).decode(),
        "mime_type": mime_map.get(p.suffix.lower(), "image/jpeg"),
        "size_bytes": len(data),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="WeChat Moments Poster MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind for HTTP transports (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for HTTP transports (default: 8765)",
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        # For SSE/HTTP, we need to run via ASGI
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport=args.transport)
