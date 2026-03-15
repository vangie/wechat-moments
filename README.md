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
brew tap vangie/tap
brew install wechat-moments
```

### Development

```bash
git clone https://github.com/vangie/wechat-moments
cd wechat-moments
uv sync
```

## Usage

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

### MCP Server (for OpenClaw)

```bash
wx-pyq-mcp
```

Exposes 4 tools:

| Tool | Description |
|------|-------------|
| `prepare_post(text, images)` | Stage assets, generate preview image, return `post_id` |
| `submit_post(post_id)` | Execute ADB flow and publish to Moments |
| `get_device_status()` | Check ADB connection and app installation |
| `take_screenshot()` | Capture current phone screen for debugging |

**Typical OpenClaw workflow:**

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

## Testing

```bash
# Unit + FSM identify tests (no phone needed)
uv run pytest tests/unit/ tests/fsm/ -v

# End-to-end (phone required)
uv run pytest -m e2e

# Collect FSM fixtures from real device (run once)
wx-pyq collect-fixtures -o tests/fsm/fixtures/
```
