#!/bin/bash

# Local Tool Server Setup Script
# Run with: sudo ./setup_tool_server.sh

set -e



#YOUR SOFTWARE CONFIGURATION HERE
TARGET_USER="danhvuive"
USER_HOME="/mnt/e/workspace/tma/tma_agent/test_env"
TOOL_SERVER_API_KEY="API_KEY_PLACEHOLDER"
MEDTHOD="pip" # Options: pip, docker,github
SOFTWARE_PIP="open-webui"
SOFTWARE_DOCKER="openwebui/open-webui:latest"
SOFTWARE_REPO="https://github.com/open-webui/open-webui.git"
WORKING_DIRECTORY="$USER_HOME/openwebui"
MCP_HOST="0.0.0.0"
MCP_PORT="3001"
API_PORT="8000"
SOFTWARE_PORT="4546"
LOG_DIR="$USER_HOME/logs"
VENV_PATH="$USER_HOME/tool_server_env"
SERVICE_NAME="toolserver"
SOFTWARE_NAME="open-webui-custom"

TARGET_USER="${TARGET_USER:-ubuntu}"
USER_HOME="${USER_HOME:-/home/$TARGET_USER}"

TOOL_SERVER_API_KEY="${TOOL_SERVER_API_KEY:-API_KEY_PLACEHOLDER}"

SOFTWARE_REPO="${SOFTWARE_REPO:-https://github.com/open-webui/open-webui.git}"
SOFTWARE_PIP="${SOFTWARE_PIP:-open-webui}"
SOFTWARE_DOCKER="${SOFTWARE_DOCKER:-openwebui/open-webui:latest}"

WORKING_DIRECTORY="${WORKING_DIRECTORY:-$USER_HOME/openwebui}"

MCP_HOST="${MCP_HOST:-0.0.0.0}"
MCP_PORT="${MCP_PORT:-3001}"
API_PORT="${API_PORT:-8000}"
SOFTWARE_PORT="${SOFTWARE_PORT:-4546}"

LOG_DIR="${LOG_DIR:-$USER_HOME/vm_logs}"

VENV_PATH="${VENV_PATH:-$USER_HOME/tool_server_env}"

SERVICE_NAME="${SERVICE_NAME:-toolserver}"


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

if [ "$EUID" -ne 0 ]; then 
    log_error "Please run as root (use sudo)"
    exit 1
fi

if ! id "$TARGET_USER" &>/dev/null; then
    log_error "User $TARGET_USER does not exist. Please create the user first or set TARGET_USER variable."
    exit 1
fi

log_info "============================================"
log_info "Tool Server Setup Configuration"
log_info "============================================"
log_info "Target User: $TARGET_USER"
log_info "Home Directory: $USER_HOME"
log_info "Working Directory: $WORKING_DIRECTORY"
log_info "MCP Port: $MCP_PORT"
log_info "API Port: $API_PORT"
log_info "OpenWebUI Port: $SOFTWARE_PORT"
log_info "Log Directory: $LOG_DIR"
log_info "============================================"

log_info "Updating system packages..."

log_info "Updating package list..."
if ! sudo apt-get update 2>/dev/null; then
    log_info "Critical error during apt-get update. Exiting."
    exit 1
fi

log_info "Upgrading installed packages..."
if ! sudo apt-get upgrade -y; then
    log_info "Failed to upgrade packages. Exiting."
    exit 1
fi

log_info "Installing required packages..."
apt-get install -y \
    python3-pip \
    python3-venv \
    docker.io \
    docker-compose \
    curl \
    jq \
    htop \
    git \
    vim \
    inotify-tools \
    screen

if ! getent group docker > /dev/null 2>&1; then
    log_info "Creating docker group..."
    groupadd docker
fi

log_info "Adding $TARGET_USER to docker and sudo groups..."
usermod -aG docker "$TARGET_USER"
usermod -aG sudo "$TARGET_USER"

log_info "Creating directories..."
sudo -u "$TARGET_USER" mkdir -p "$VENV_PATH"
sudo -u "$TARGET_USER" mkdir -p "$LOG_DIR"
sudo -u "$TARGET_USER" mkdir -p "$(dirname "$WORKING_DIRECTORY")"
sudo -u "$TARGET_USER" touch "$USER_HOME/debug.log"

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
# sudo -u danhvuive python3 -m venv /home/danhvuive/tool_server_env
sudo -u "$TARGET_USER" python3 -m venv "$VENV_PATH"

sudo -u "$TARGET_USER" "$VENV_PATH/bin/pip" install --upgrade pip
sudo -u "$TARGET_USER" "$VENV_PATH/bin/pip" install -r "$USER_HOME/requirements.txt"

# log_info "Cloning and installing open-webui from: $SOFTWARE_REPO"
# if [ ! -d "$WORKING_DIRECTORY" ]; then
#     sudo -u "$TARGET_USER" git clone "$SOFTWARE_REPO" "$WORKING_DIRECTORY"
# fi

sudo -u "$TARGET_USER" "$VENV_PATH/bin/pip" install open-webui

log_info "Creating .env file..."
cat > "$USER_HOME/.env" << EOF
TOOL_SERVER_API_KEY="$TOOL_SERVER_API_KEY"
WORKING_DIRECTORY="$WORKING_DIRECTORY"

MCP_HOST="$MCP_HOST"
MCP_PORT="$MCP_PORT"
API_PORT="$API_PORT"
SOFTWARE_PORT="$SOFTWARE_PORT"

LOG_DIR="$LOG_DIR"
EOF

log_info "Creating start_server.sh..."
cat > "$USER_HOME/start_server.sh" << EOF
#!/bin/bash
cd "$USER_HOME"

export VIRTUAL_ENV="$VENV_PATH"
export PATH="\$VIRTUAL_ENV/bin:\$PATH"

source "$VENV_PATH/bin/activate"


echo "Starting Tool Server..."
python tool_server.py
EOF

log_info "Creating systemd service: $SERVICE_NAME"
sudo tee "/etc/systemd/system/$SERVICE_NAME.service" << EOF
[Unit]
Description=Agent MCP Tool Server
After=network.target docker.service

[Service]
Type=exec
User=$TARGET_USER
Group=docker
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



log_info "Starting Docker service..."
systemctl enable docker
systemctl start docker

log_info "Enabling $SERVICE_NAME service..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME.service"

log_info "Setting permissions..."
chown -R "$TARGET_USER:$TARGET_USER" "$USER_HOME"
chmod +x "$USER_HOME/start_server.sh"
chmod 600 "$USER_HOME/.env"


sudo systemctl daemon-reload
sudo systemctl restart $SERVICE_NAME



log_info "Creating systemd service for software: $"



cat > "$USER_HOME/setup_complete.txt" << EOF
Tool Server setup completed at $(date)

Configuration:
- User: $TARGET_USER
- Home: $USER_HOME
- Working Directory: $WORKING_DIRECTORY
- Tool Server API: http://localhost:$API_PORT
- MCP WebSocket: ws://localhost:$MCP_PORT
- OpenWebUI: http://localhost:$SOFTWARE_PORT
- Docker: Available

IMPORTANT: Before starting the service, you must:
1. Extract tool_server.py from the cloud-init file and place it at:
   $USER_HOME/tool_server.py

2. Extract process_controller.py from the cloud-init file and place it at:
   $USER_HOME/process_controller.py

Then start the service:
sudo systemctl start $SERVICE_NAME

Manual start:
$USER_HOME/start_server.sh

Check service status:
sudo systemctl status $SERVICE_NAME

View logs:
sudo journalctl -u $SERVICE_NAME -f

Stop service:
sudo systemctl stop $SERVICE_NAME

Delete service:
sudo systemctl stop $SERVICE_NAME
sudo systemctl disable $SERVICE_NAME
sudo rm /etc/systemd/system/$SERVICE_NAME.service
sudo systemctl daemon-reload
sudo systemctl reset-failed

or

sudo systemctl stop toolserver
sudo systemctl disable toolserver
sudo rm /etc/systemd/system/toolserver.service
sudo systemctl daemon-reload
sudo systemctl reset-failed

EOF
chown "$TARGET_USER:$TARGET_USER" "$USER_HOME/setup_complete.txt"



#START YOUR SOFTWARE HERE
# log_info "Starting $SOFTWARE_NAME in detached screen session..."
# # screen -dmS open-webui -L -Logfile "\$LOG_FILE" bash -c "cd $USER_HOME && source $VENV_PATH/bin/activate && PORT=$SOFTWARE_PORT $USER_HOME/backend/start.sh"
# screen -dmS $SOFTWARE_NAME -L -Logfile "$LOG_DIR/$SOFTWARE_NAME.log" bash -c "cd $USER_HOME && source $VENV_PATH/bin/activate && PORT=$SOFTWARE_PORT $WORKING_DIRECTORY/backend/start.sh"
# sleep 20

log_info "Starting $SOFTWARE_NAME using pip server..."
# serve and log
screen -dmS $SOFTWARE_NAME -L -Logfile "$LOG_DIR/$SOFTWARE_NAME.log" bash -c "cd $USER_HOME && source $VENV_PATH/bin/activate && $VENV_PATH/bin/open-webui serve --host 0.0.0.0 --port $SOFTWARE_PORT"
sleep 20

log_info "============================================"
log_info "Setup complete!"
log_info "============================================"
log_warn "IMPORTANT: You must extract the Python files:"
log_warn "  1. tool_server.py -> $USER_HOME/tool_server.py"
log_warn "  2. process_controller.py -> $USER_HOME/process_controller.py"
log_warn "IMPORTANT: You must extract the Python files:"
log_warn ""
log_warn "After adding those files, run:"
log_warn "  sudo systemctl start $SERVICE_NAME"
log_warn ""
log_info "Please log out and log back in for group changes to take effect"
log_info "Configuration details: $USER_HOME/setup_complete.txt"