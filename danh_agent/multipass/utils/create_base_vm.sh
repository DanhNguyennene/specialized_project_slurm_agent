#!/bin/bash

VM_NAME="${1:-test-vm}"

# Load API key from .env file
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
    if [ -z "$TOOL_SERVER_API_KEY" ]; then
        echo "Error: TOOL_SERVER_API_KEY not found in .env file"
        exit 1
    fi
else
    echo "Error: .env file not found"
    exit 1
fi

# Read the cloud-init template and replace placeholder
CONFIG_WITH_SECRET=$(sed "s/API_KEY_PLACEHOLDER/${TOOL_SERVER_API_KEY}/g" ./image-init.yaml)

# Ensure the API key variable is unset after use
unset TOOL_SERVER_API_KEY

# Launch new VM with the configuration
echo "Creating $VM_NAME..."
echo "$CONFIG_WITH_SECRET" | multipass launch bionic --name "$VM_NAME" --cloud-init -

# Wait for setup to complete
echo "Setting up $VM_NAME (this may take a few minutes)..."
multipass exec "$VM_NAME" -- cloud-init status --wait

echo "VM $VM_NAME created successfully!"
echo "Connect with: multipass shell $VM_NAME"

# Show what's installed
echo ""
echo "=== Installed Software ==="
multipass exec "$VM_NAME" -- docker --version
multipass exec "$VM_NAME" -- python3 --version
multipass exec "$VM_NAME" -- git --version

multipass stop "$VM_NAME"