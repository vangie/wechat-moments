#!/bin/bash
#
# Deploy MCP server configuration to remote mcporter
#
# Usage:
#   ./scripts/deploy-mcp-remote.sh [remote] [endpoint]
#   ./scripts/deploy-mcp-remote.sh myserver
#   ./scripts/deploy-mcp-remote.sh ssh://user@host:2222
#   ./scripts/deploy-mcp-remote.sh myserver http://192.168.1.100:8765/sse
#
# Environment variables (can be set in .env.local):
#   REMOTE_EXEC     Remote execution target (e.g., myserver, ssh://user@host:2222)
#   MCP_ENDPOINT    Full MCP endpoint URL (e.g., http://192.168.1.100:8765/sse)
#
# Remote target formats:
#   myserver               SSH config alias
#   user@host              user@host
#   user@host:2222         user@host with port
#   ssh://user@host:2222   explicit SSH protocol
#
# This script:
# 1. Detects your local IP (or uses MCP_ENDPOINT)
# 2. Updates ~/.openclaw/workspace/config/mcporter.json on the remote machine
#
# Prerequisites:
# - SSH access to the remote machine
# - jq installed on the remote machine

set -e

# Load .env.local if exists
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
if [ -f "$PROJECT_ROOT/.env.local" ]; then
    set -a
    source "$PROJECT_ROOT/.env.local"
    set +a
fi

# Parse arguments
REMOTE_TARGET="${REMOTE_EXEC:-}"
MCP_URL="${MCP_ENDPOINT:-}"

for arg in "$@"; do
    if [ -z "$REMOTE_TARGET" ]; then
        REMOTE_TARGET="$arg"
    elif [ -z "$MCP_URL" ]; then
        MCP_URL="$arg"
    fi
done

if [ -z "$REMOTE_TARGET" ]; then
    echo "Usage: $0 [remote] [endpoint]"
    echo ""
    echo "Remote target formats:"
    echo "  myserver               SSH config alias"
    echo "  user@host              user@host"
    echo "  user@host:2222         user@host with port"
    echo "  ssh://user@host:2222   explicit SSH protocol"
    echo ""
    echo "Or set REMOTE_EXEC in .env.local:"
    echo "  echo 'REMOTE_EXEC=myserver' >> .env.local"
    exit 1
fi

# Parse REMOTE_TARGET: extract protocol and port
EXEC_PROTOCOL="ssh"
EXEC_TARGET="$REMOTE_TARGET"
SSH_PORT=""

# Check for protocol prefix (e.g., ssh://)
if [[ "$EXEC_TARGET" =~ ^([a-z]+):// ]]; then
    EXEC_PROTOCOL="${BASH_REMATCH[1]}"
    EXEC_TARGET="${EXEC_TARGET#*://}"
fi

# Only SSH is supported for now
if [ "$EXEC_PROTOCOL" != "ssh" ]; then
    echo "Error: Unsupported protocol '$EXEC_PROTOCOL'. Only 'ssh' is supported."
    exit 1
fi

# Extract port if present (user@host:port)
if [[ "$EXEC_TARGET" =~ :([0-9]+)$ ]]; then
    SSH_PORT="${BASH_REMATCH[1]}"
    EXEC_TARGET="${EXEC_TARGET%:*}"
fi

# Build SSH command
SSH_CMD="ssh"
[ -n "$SSH_PORT" ] && SSH_CMD="ssh -p $SSH_PORT"

# Auto-detect MCP endpoint if not provided
if [ -z "$MCP_URL" ]; then
    # Try macOS first, then Linux
    LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')
    if [ -z "$LOCAL_IP" ]; then
        echo "Error: Could not detect local IP. Please set MCP_ENDPOINT."
        exit 1
    fi
    MCP_URL="http://${LOCAL_IP}:8765/sse"
fi

MCPORTER_CONFIG="\$HOME/.mcporter/mcporter.json"

echo "=== WeChat Moments Poster MCP Deployment ==="
echo "Remote: $REMOTE_TARGET"
[ -n "$SSH_PORT" ] && echo "SSH Port: $SSH_PORT"
echo "MCP URL: $MCP_URL"
echo ""

# Check if we can SSH to the remote host
echo "Checking SSH connection..."
if ! $SSH_CMD -o ConnectTimeout=5 "$EXEC_TARGET" "echo 'SSH OK'" 2>/dev/null; then
    echo "Error: Cannot connect to $EXEC_TARGET via SSH"
    exit 1
fi

# Check if jq is installed on remote
echo "Checking remote dependencies..."
if ! $SSH_CMD "$EXEC_TARGET" "command -v jq" >/dev/null 2>&1; then
    echo "Error: jq is not installed on $EXEC_TARGET"
    echo "Install it with: sudo apt install jq (Debian/Ubuntu) or brew install jq (macOS)"
    exit 1
fi

# Update mcporter config
echo "Updating mcporter configuration..."

$SSH_CMD "$EXEC_TARGET" bash -s "$MCP_URL" "$MCPORTER_CONFIG" << 'REMOTE_SCRIPT'
MCP_URL="$1"
CONFIG_FILE="$2"

# Expand $HOME in path
CONFIG_FILE="${CONFIG_FILE/\$HOME/$HOME}"

# Create config directory if needed
mkdir -p "$(dirname "$CONFIG_FILE")"

# Create default config if it doesn't exist
if [ ! -f "$CONFIG_FILE" ]; then
    echo '{"mcpServers":{}}' > "$CONFIG_FILE"
fi

# Backup existing config
cp "$CONFIG_FILE" "${CONFIG_FILE}.bak"

# Update config with jq
jq --arg url "$MCP_URL" '
  .mcpServers["wechat-moments"] = {
    "baseUrl": $url,
    "transport": "sse"
  }
' "$CONFIG_FILE" > "${CONFIG_FILE}.tmp" && mv "${CONFIG_FILE}.tmp" "$CONFIG_FILE"

echo "Configuration updated:"
jq '.mcpServers["wechat-moments"]' "$CONFIG_FILE"
REMOTE_SCRIPT

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "mcporter configuration updated at:"
echo "  ~/.mcporter/mcporter.json"
echo ""
echo "Next steps:"
echo ""
echo "1. Start the MCP server on your local machine:"
echo "   cd $PROJECT_ROOT && make mcp-remote"
echo ""
echo "2. Install mcporter (if not already):"
echo "   $SSH_CMD $EXEC_TARGET 'npm install -g mcporter'"
echo ""
echo "3. Test the MCP tool:"
echo "   $SSH_CMD $EXEC_TARGET 'mcporter call wechat-moments.list_tools'"
