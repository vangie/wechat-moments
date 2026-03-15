#!/bin/bash
#
# Start MCP server for remote access via SSE transport
#
# Usage:
#   ./scripts/mcp-remote.sh [host] [port]
#
# Default: 0.0.0.0:8765

set -e

HOST="${1:-0.0.0.0}"
PORT="${2:-8765}"

# Detect local IP for display
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')

echo "Starting MCP server on http://${HOST}:${PORT}/sse"
if [ -n "$LOCAL_IP" ]; then
    echo "Remote clients connect to: http://${LOCAL_IP}:${PORT}/sse"
fi

exec uv run wx-pyq-mcp --transport sse --host "$HOST" --port "$PORT"
