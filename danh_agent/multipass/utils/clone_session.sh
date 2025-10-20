#clone and start new multipass instance
#!/bin/bash
VM_NAME="${1:-test1}"
BASE_VM_NAME="${2:-test-vm}"

multipass clone "$BASE_VM_NAME" --name "$VM_NAME" 
multipass start "$VM_NAME"
multipass exec "$VM_NAME" -- cloud-init status --wait
multipass exec "$VM_NAME" -- bash -c "cd /home/ubuntu && ./start_server.sh" 
# return IP address of the new VM
VM_IP=$(multipass info "$VM_NAME" | grep "IPv4" | awk '{print $2}')
echo "VM $VM_NAME started successfully at IP: $VM_IP"
echo "Connect with: multipass shell $VM_NAME"