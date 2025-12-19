#!/bin/bash
# Start Slurm MCP Server

cd "$(dirname "$0")"

# Configuration
export SLURM_API_KEY_ADMIN="${SLURM_API_KEY_ADMIN:-changeme}"
export MCP_HOST="${MCP_HOST:-0.0.0.0}"
export MCP_PORT="${MCP_PORT:-3001}"

echo "Starting Slurm MCP Server..."
echo "Host: $MCP_HOST"
echo "Port: $MCP_PORT"
echo "API Key: ${SLURM_API_KEY_ADMIN:0:4}****"

python slurm_mcp_server.py
