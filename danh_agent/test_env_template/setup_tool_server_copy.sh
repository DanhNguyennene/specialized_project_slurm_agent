#!/bin/bash

# Slurm Tool Server Setup Script
# Run with: ./setup_slurm_tool_server.sh (as root)

set -e

# SLURM TOOL SERVER CONFIGURATION
TARGET_USER="root"
USER_HOME="/mnt/e/workspace/tma/tma_agent/test_env"

SLURM_API_KEY_root="API_KEY_PLACEHOLDER"

MCP_HOST="0.0.0.0"
MCP_PORT="3001"
API_PORT="8000"

LOG_DIR="$USER_HOME/logs"
VENV_PATH="$USER_HOME/tool_server_env"
SERVICE_NAME="slurm-toolserver"

# Apply defaults
TARGET_USER="${TARGET_USER:-ubuntu}"
USER_HOME="${USER_HOME:-/home/$TARGET_USER}"
TOOL_SERVER_API_KEY="${TOOL_SERVER_API_KEY:-API_KEY_PLACEHOLDER}"
MCP_HOST="${MCP_HOST:-0.0.0.0}"
MCP_PORT="${MCP_PORT:-3001}"
API_PORT="${API_PORT:-8000}"
LOG_DIR="${LOG_DIR:-$USER_HOME/logs}"
VENV_PATH="${VENV_PATH:-$USER_HOME/tool_server_env}"
SERVICE_NAME="${SERVICE_NAME:-slurm-toolserver}"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Verify running as root
if [ "$EUID" -ne 0 ]; then 
    log_error "Please run as root"
    exit 1
fi

# Verify user exists
if ! id "$TARGET_USER" &>/dev/null; then
    log_error "User $TARGET_USER does not exist. Please create the user first or set TARGET_USER variable."
    exit 1
fi

# Verify Slurm is installed
if ! command -v sinfo &> /dev/null; then
    log_error "Slurm is not installed or not in PATH. Please install Slurm first."
    exit 1
fi

log_info "============================================"
log_info "Slurm Tool Server Setup Configuration"
log_info "============================================"
log_info "Target User: $TARGET_USER"
log_info "Home Directory: $USER_HOME"
log_info "MCP Port: $MCP_PORT"
log_info "API Port: $API_PORT"
log_info "Log Directory: $LOG_DIR"
log_info "Slurm Version: $(sinfo --version 2>&1 | head -1)"
log_info "============================================"

log_info "Updating system packages..."
if ! apt-get update 2>/dev/null; then
    log_error "Critical error during apt-get update. Exiting."
    exit 1
fi

log_info "Upgrading installed packages..."
if ! apt-get upgrade -y; then
    log_warn "Failed to upgrade packages. Continuing..."
fi

log_info "Installing required packages..."
apt-get install -y \
    python3-pip \
    python3-venv \
    curl \
    jq \
    htop \
    git \
    vim \
    inotify-tools \
    screen

log_info "Creating directories..."
mkdir -p "$VENV_PATH"
mkdir -p "$LOG_DIR"
touch "$USER_HOME/debug.log"

log_info "Creating requirements.txt..."
cat > "$USER_HOME/requirements.txt" << 'EOF'
fastapi
aiohttp
uvicorn[standard]
requests
psutil
python-dotenv
mcp
fastmcp
itsdangerous
EOF

log_info "Creating Python virtual environment..."
python3 -m venv "$VENV_PATH"

log_info "Installing Python packages..."
"$VENV_PATH/bin/pip" install --upgrade pip
"$VENV_PATH/bin/pip" install -r "$USER_HOME/requirements.txt"

log_info "Creating .env file..."
cat > "$USER_HOME/.env" << EOF
TOOL_SERVER_API_KEY="$TOOL_SERVER_API_KEY"

MCP_HOST="$MCP_HOST"
MCP_PORT="$MCP_PORT"
API_PORT="$API_PORT"

LOG_DIR="$LOG_DIR"
EOF

log_info "Creating start_server.sh..."
cat > "$USER_HOME/start_server.sh" << EOF
#!/bin/bash
cd "$USER_HOME"

export VIRTUAL_ENV="$VENV_PATH"
export PATH="\$VIRTUAL_ENV/bin:\$PATH"

source "$VENV_PATH/bin/activate"

echo "Starting Slurm Tool Server..."
python tool_server.py
EOF

log_info "Creating systemd service: $SERVICE_NAME"
tee "/etc/systemd/system/$SERVICE_NAME.service" << EOF
[Unit]
Description=Slurm MCP Tool Server
After=network.target slurmd.service slurmctld.service

[Service]
Type=exec
User=$TARGET_USER
WorkingDirectory=$USER_HOME/
EnvironmentFile=$USER_HOME/.env

Environment=PATH=$VENV_PATH/bin:/usr/bin:/bin
ExecStart=$USER_HOME/start_server.sh
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

NoNewPrivileges=yes
ReadWritePaths=$USER_HOME
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF

log_info "Enabling $SERVICE_NAME service..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME.service"

log_info "Setting permissions..."
chown -R "$TARGET_USER:$TARGET_USER" "$USER_HOME"
chmod +x "$USER_HOME/start_server.sh"
chmod 600 "$USER_HOME/.env"

log_info "Reloading systemd..."
systemctl daemon-reload

cat > "$USER_HOME/setup_complete.txt" << EOF
Slurm Tool Server setup completed at $(date)

Configuration:
- User: $TARGET_USER
- Home: $USER_HOME
- Tool Server API: http://localhost:$API_PORT
- MCP WebSocket: ws://localhost:$MCP_PORT
- Slurm Version: $(sinfo --version 2>&1 | head -1)

IMPORTANT: Before starting the service, you must:
1. Extract tool_server.py from the cloud-init file and place it at:
   $USER_HOME/tool_server.py

2. Extract process_controller.py from the cloud-init file and place it at:
   $USER_HOME/process_controller.py

These files should include Slurm command integration (sbatch, squeue, scancel, sinfo, etc.)

Then start the service:
systemctl start $SERVICE_NAME

Manual start:
$USER_HOME/start_server.sh

Check service status:
systemctl status $SERVICE_NAME

View logs:
journalctl -u $SERVICE_NAME -f

Stop service:
systemctl stop $SERVICE_NAME

Delete service:
systemctl stop $SERVICE_NAME
systemctl disable $SERVICE_NAME
rm /etc/systemd/system/$SERVICE_NAME.service
systemctl daemon-reload
systemctl reset-failed

Useful Slurm Commands:
- sinfo: View cluster information
- squeue: View job queue
- sbatch: Submit batch job
- scancel: Cancel job
- scontrol: Administrative commands
- sacct: Job accounting information
EOF
chown "$TARGET_USER:$TARGET_USER" "$USER_HOME/setup_complete.txt"

log_info "============================================"
log_info "Setup complete!"
log_info "============================================"
log_warn "IMPORTANT: You must extract the Python files:"
log_warn "  1. tool_server.py -> $USER_HOME/tool_server.py"
log_warn "  2. process_controller.py -> $USER_HOME/process_controller.py"
log_warn ""
log_warn "Make sure these files include Slurm command wrappers for:"
log_warn "  - sbatch (submit jobs)"
log_warn "  - squeue (query jobs)"
log_warn "  - scancel (cancel jobs)"
log_warn "  - sinfo (cluster info)"
log_warn "  - sacct (job accounting)"
log_warn ""
log_warn "After adding those files, run:"
log_warn "  systemctl start $SERVICE_NAME"
log_warn ""
log_info "Configuration details: $USER_HOME/setup_complete.txt"
log_info "Slurm integration ready!"