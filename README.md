# wechat-moments

[![PyPI version](https://img.shields.io/pypi/v/wechat-moments.svg)](https://pypi.org/project/wechat-moments/)
[![CI](https://github.com/vangie/wechat-moments/actions/workflows/ci.yml/badge.svg)](https://github.com/vangie/wechat-moments/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

Post to WeChat Moments via ADB automation. Controls an Android phone running WeChat using a deterministic FSM — no LLM required for UI interaction.

## Requirements

- Python 3.12+
- Android phone with USB debugging enabled, WeChat installed

> **Note:** [ADBKeyboard](https://github.com/senzhk/ADBKeyBoard) is required for Chinese text input and will be installed automatically on first use.

## Installation

### pipx (recommended)

```bash
pipx install wechat-moments
```

### uv tool

```bash
uv tool install wechat-moments
```

### Homebrew (macOS)

```bash
brew tap vangie/formula
brew install wechat-moments
```

## Usage

### OpenClaw Integration

To integrate with [OpenClaw](https://github.com/anthropics/openclaw) or other MCP clients:

#### Local Setup (stdio mode)

If the MCP client and Android phone are on the same machine, use stdio transport (recommended):

Add to your MCP client config (e.g., `~/.mcporter/mcporter.json`):

```json
{
  "mcpServers": {
    "wechat-moments": {
      "command": "wx-pyq-mcp"
    }
  }
}
```

#### Remote Setup (SSE mode)

If the Android phone is connected to a different machine:

1. On the machine with the phone, start the MCP server:

```bash
wx-pyq-mcp --transport sse --host 0.0.0.0 --port 8765
```

2. On the remote machine, configure the MCP client:

```json
{
  "mcpServers": {
    "wechat-moments": {
      "baseUrl": "http://<phone-machine-ip>:8765/sse",
      "transport": "sse"
    }
  }
}
```

### CLI

```bash
# Check device connection
wx-pyq status

# Post with text only
wx-pyq post "今天天气真好"

# Post with images (local paths or URLs, max 9)
wx-pyq post "周末出游" -i photo1.jpg -i photo2.jpg

# Post without preview confirmation prompt
wx-pyq post "自动发布" -i photo.jpg --no-preview

# Collect FSM test fixtures (run once with phone connected)
wx-pyq collect-fixtures -o tests/fsm/fixtures/

# Clean up expired staging / archive dirs
wx-pyq cleanup
```

### MCP Server

The MCP server exposes tools for AI agents to post to WeChat Moments.

```bash
# Start MCP server (stdio transport, for local use)
wx-pyq-mcp

# Start MCP server with SSE transport (for remote access)
wx-pyq-mcp --transport sse --host 0.0.0.0 --port 8765
```

#### Available Tools

| Tool | Description |
|------|-------------|
| `prepare_post(text, images)` | Stage assets, generate preview image, return `post_id` |
| `submit_post(post_id)` | Execute ADB flow and publish to Moments |
| `get_device_status()` | Check ADB connection and app installation |
| `take_screenshot()` | Capture current phone screen for debugging |

#### Typical Workflow

```
prepare_post("text", ["image.jpg"])
  → returns { post_id, preview_path, ... }
  → show preview_path to user for confirmation (optional)
submit_post(post_id)
  → returns { status: "success", archive_path: "..." }
```

## Architecture

```
CLI / MCP Server
      │
   preview.py   ← prepare_post: stage images, generate layout preview
      │
   submit.py    ← execute_submit: lock + FSM + archive + history
      │
  ┌───┴──────────────────────────────────┐
  │ UI FSM (poster.py)                   │  ← concurrent with ↓
  │ LAUNCH → DETECT_TAB → NAV_DISCOVER   │
  │ → OPEN_MOMENTS → [DISCARD_DIALOG]    │
  │ → SELECT_IMAGES → INPUT_TEXT → DONE  │
  └──────────────────────────────────────┘
  │ Image FSM (images.py, background thread)
  │ IDLE → PUSHING → SCANNING → READY → CLEANUP
      │
    adb.py   ← ADB commands (screenshot, tap, dump UI, push files)
    cv.py    ← tab detection, checkmark counting
    ime.py   ← ADBKeyboard Chinese text input
```

## Device Profiles

UI coordinates are stored in `profiles/<device_serial>.json`. Huawei defaults are in `profiles/huawei_default.json`. Run `wx-pyq calibrate` to create a profile for a new device.

## Data Directory

```
~/.local/share/wechat-moments/
├── history.jsonl        # append-only event log
├── submit.lock          # global mutex
├── staging/<post_id>/   # active/pending posts
└── archive/<post_id>/   # completed posts (preview + meta kept 30 days)
```

## License

MIT
