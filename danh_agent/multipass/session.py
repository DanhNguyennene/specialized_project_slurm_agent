

# This class controlls vm sessions, by creating a base image, clone session and distributed it accordingly.
import os
import requests
import subprocess
import os
class SessionController:
    def __init__(self,base_yaml="image-init.yaml", bash_script_dir="utils"):
        self.pwd = os.getcwd()
        self.base_yaml = base_yaml
        self.bash_script_dir = self.pwd + "/" + bash_script_dir

    def create_vm_with_api_key(self,vm_name="test-vm"):
        try:
            # Load API key from .env file
            if os.path.exists(".env"):
                with open(".env", "r") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            if '=' in line:
                                key, value = line.split('=', 1)
                                if key == "TOOL_SERVER_API_KEY":
                                    tool_server_api_key = value
                                    break
                    else:
                        print("Error: TOOL_SERVER_API_KEY not found in .env file")
                        return False
            else:
                print("Error: .env file not found")
                return False

            # Read the cloud-init template and replace placeholder
            if not os.path.exists("./image-init.yaml"):
                print("Error: image-init.yaml file not found")
                return False
                
            with open("./image-init.yaml", "r") as f:
                config_template = f.read()
            
            config_with_secret = config_template.replace("API_KEY_PLACEHOLDER", tool_server_api_key)

            # Launch new VM with the configuration
            print(f"Creating {vm_name}...")
            subprocess.run([
                "multipass", "launch", "bionic", 
                "--name", vm_name, 
                "--cloud-init", "-"
            ], input=config_with_secret, text=True, check=True)

            # Wait for setup to complete
            print(f"Setting up {vm_name} (this may take a few minutes)...")
            try:
                subprocess.run([
                    "multipass", "exec", vm_name, "--", 
                    "cloud-init", "status", "--wait"
                ], check=True, timeout=1000)
            except subprocess.CalledProcessError as e:
                print(f"Error during cloud-init status check: {e}")
            print(f"VM {vm_name} created successfully!")
            print(f"Connect with: multipass shell {vm_name}")

            # Show what's installed
            print("\n=== Installed Software ===")
            
            # Check docker version
            try:
                result = subprocess.run([
                    "multipass", "exec", vm_name, "--", "docker", "--version"
                ], capture_output=True, text=True, check=True)
                print(result.stdout.strip())
            except subprocess.CalledProcessError:
                print("Docker: Not installed or not accessible")
            
            # Check python version
            try:
                result = subprocess.run([
                    "multipass", "exec", vm_name, "--", "python3", "--version"
                ], capture_output=True, text=True, check=True)
                print(result.stdout.strip())
            except subprocess.CalledProcessError:
                print("Python3: Not installed or not accessible")
            
            try:
                result = subprocess.run([
                    "multipass", "exec", vm_name, "--", "git", "--version"
                ], capture_output=True, text=True, check=True)
                print(result.stdout.strip())
            except subprocess.CalledProcessError:
                print("Git: Not installed or not accessible")

            subprocess.run(["multipass", "stop", vm_name], check=True)
            
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"Error occurred: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error: {e}")
            return False
    def clone_and_start_vm(self,vm_name="test1", base_vm_name="test-vm"):
        try:
            subprocess.run(["multipass", "clone", base_vm_name, "--name", vm_name], check=True)
            
            subprocess.run(["multipass", "start", vm_name], check=True)
            
            subprocess.run(["multipass", "exec", vm_name, "--", "cloud-init", "status", "--wait"], check=True)
            
            subprocess.run(["multipass", "exec", vm_name, "--", "bash", "-c", "cd /home/ubuntu && ./start_server.sh"], check=True)
            
            result = subprocess.run(["multipass", "info", vm_name], capture_output=True, text=True, check=True)
            vm_ip = None
            for line in result.stdout.split('\n'):
                if 'IPv4' in line:
                    vm_ip = line.split()[1]
                    break
            
            if vm_ip:
                print(f"VM {vm_name} started successfully at IP: {vm_ip}")
                print(f"Connect with: multipass shell {vm_name}")
                return vm_ip
            else:
                print("Warning: Could not retrieve VM IP address")
                return None
                
        except subprocess.CalledProcessError as e:
            print(f"Error occurred: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error: {e}")
            return None


session = SessionController()
session.create_vm_with_api_key("test-vm")
session.clone_and_start_vm("test1", "test-vm")