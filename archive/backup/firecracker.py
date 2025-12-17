"""Universal Execution Framework using Firecracker MicroVMs
This provides true isolation and can run ANYTHING - Docker, K8s, web apps, mobile apps, etc.
"""

import asyncio
import json
import subprocess
import tempfile
import os
import time
import uuid
import requests
import paramiko
from typing import Dict, Any, List, Optional
import yaml
from pathlib import Path
import tarfile
import io

from mcp_tools import MCPToolServer, MCPTool

class FirecrackerVMManager:
    """Manage Firecracker microVMs for universal code execution"""
    
    def __init__(self,
                kernel_path: str = "/opt/firecracker/vmlinux.bin",
                rootfs_path: str = "/opt/firecracker/rootfs.ext4", 
                firecracker_binary: str = "/usr/local/bin/firecracker"):
        self.firecracker_binary = firecracker_binary
        self.vm_instances = {}
        self.base_images = {}
        self.kernel_path = kernel_path
        self.rootfs_path = rootfs_path
        self.init_base_images()
    
    def init_base_images(self):
        """Initialize base VM images for different environments"""
        self.base_images = {
            "ubuntu22": {
                "kernel": self.kernel_path,
                "rootfs": self.rootfs_path,
                "description": "Ubuntu 22.04 with Docker, Node.js, Python, Go, etc.",
                "capabilities": ["docker", "kubernetes", "web", "python", "node", "go", "rust", "flutter"]
            },
            "alpine": {
                "kernel": self.kernel_path,
                "rootfs": self.rootfs_path,
                "description": "Lightweight Alpine Linux for basic tasks",
                "capabilities": ["python", "node", "go", "docker"]
            },
            "development": {
                "kernel": self.kernel_path,
                "rootfs": self.rootfs_path,
                "description": "Full development environment with all tools",
                "capabilities": ["docker", "kubernetes", "flutter", "android", "ios", "web", "all"]
            }
        }
    
    def register_tools(self, mcp_server):
        """Register universal execution tools with MCP server"""
        
        # Universal execution tool
        mcp_server.tools["universal_execute"] = mcp_server.MCPTool(
            name="universal_execute",
            description="Execute any type of application in isolated MicroVM",
            parameters={
                "type": "object",
                "properties": {
                    "execution_type": {
                        "type": "string",
                        "enum": ["docker", "kubernetes", "web_app", "flutter", "python", "node", 
                                "go", "rust", "java", "android", "ios", "custom"],
                        "description": "Type of execution environment needed"
                    },
                    "source_files": {
                        "type": "object",
                        "description": "Source files (filename: content)",
                        "additionalProperties": {"type": "string"}
                    },
                    "main_command": {
                        "type": "string", 
                        "description": "Main command to execute"
                    },
                    "setup_commands": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Setup commands to run before main execution"
                    },
                    "environment_vars": {
                        "type": "object",
                        "description": "Environment variables",
                        "additionalProperties": {"type": "string"}
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Execution timeout in seconds (default: 300)",
                        "default": 300
                    },
                    "memory_mb": {
                        "type": "integer", 
                        "description": "Memory allocation in MB (default: 512)",
                        "default": 512
                    },
                    "cpu_count": {
                        "type": "integer",
                        "description": "Number of vCPUs (default: 1)",
                        "default": 1
                    },
                    "network_enabled": {
                        "type": "boolean",
                        "description": "Enable network access (default: false for security)",
                        "default": False
                    },
                    "persistent_storage": {
                        "type": "boolean",
                        "description": "Keep VM running for multiple commands (default: false)",
                        "default": False
                    }
                },
                "required": ["execution_type", "main_command"]
            }
        )
        
        # VM Management tool  
        mcp_server.tools["vm_manage"] = mcp_server.MCPTool(
            name="vm_manage",
            description="Manage MicroVMs (list, stop, remove, etc.)",
            parameters={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["list", "stop", "remove", "stop_all", "get_info", "create_snapshot"],
                        "description": "VM management operation"
                    },
                    "vm_id": {
                        "type": "string",
                        "description": "VM instance ID (for specific operations)"
                    }
                },
                "required": ["operation"]
            }
        )
        
        # Environment info tool
        mcp_server.tools["execution_environments"] = mcp_server.MCPTool(
            name="execution_environments", 
            description="Get information about available execution environments",
            parameters={
                "type": "object",
                "properties": {
                    "show_capabilities": {
                        "type": "boolean",
                        "description": "Show detailed capabilities of each environment",
                        "default": True
                    }
                }
            }
        )
    
    async def universal_execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute any type of application in isolated MicroVM"""
        execution_type = params.get("execution_type")
        # to MCP
        source_files = params.get("source_files", {})
        main_command = params.get("main_command")
        setup_commands = params.get("setup_commands", [])
        environment_vars = params.get("environment_vars", {})
        timeout = params.get("timeout", 300)
        memory_mb = params.get("memory_mb", 512) 
        cpu_count = params.get("cpu_count", 1)
        network_enabled = params.get("network_enabled", False)
        persistent_storage = params.get("persistent_storage", False)
        
        base_image = self._select_base_image(execution_type)
        if not base_image:
            return {"error": f"No suitable base image for execution type: {execution_type}"}
        print(f"Using base image: {base_image}")
        print(f"Kernel path: {self.kernel_path}, Rootfs path: {self.rootfs_path}")

        print(f"Execution type: {execution_type}, Memory: {memory_mb}MB, CPU count: {cpu_count}, Network enabled: {network_enabled}")
        vm_id = f"vm_{execution_type}_{str(uuid.uuid4())[:8]}"
        
        try:
            vm_info = await self._create_vm_instance(
                vm_id=vm_id,
                base_image=base_image,
                memory_mb=memory_mb,
                cpu_count=cpu_count,
                network_enabled=network_enabled
            )
            
            if not vm_info["success"]:
                return vm_info
            
            await self._wait_for_vm_ready(vm_id)
            
            if source_files:
                transfer_result = await self._transfer_files(vm_id, source_files)
                if not transfer_result["success"]:
                    return transfer_result
            
            setup_results = []
            for cmd in setup_commands:
                result = await self._execute_command_in_vm(vm_id, cmd, environment_vars)
                setup_results.append(result)
                if result["exit_code"] != 0:
                    return {
                        "error": "Setup command failed",
                        "failed_command": cmd,
                        "setup_results": setup_results
                    }
            
            execution_start = time.time()
            main_result = await self._execute_command_in_vm(
                vm_id, main_command, environment_vars, timeout
            )
            execution_time = time.time() - execution_start
            
            # Get final results
            result = {
                "success": main_result["exit_code"] == 0,
                "vm_id": vm_id,
                "execution_type": execution_type,
                "execution_time": execution_time,
                "main_result": main_result,
                "setup_results": setup_results,
                "base_image": base_image,
                "resources": {
                    "memory_mb": memory_mb,
                    "cpu_count": cpu_count,
                    "network_enabled": network_enabled
                }
            }
            
            # Cleanup unless persistent storage requested
            if not persistent_storage:
                await self._cleanup_vm(vm_id)
                result["vm_cleaned_up"] = True
            else:
                result["vm_persistent"] = True
                result["ssh_info"] = vm_info.get("ssh_info")
            
            return result
            
        except Exception as e:
            # Always cleanup on error
            await self._cleanup_vm(vm_id)
            return {"error": f"Universal execution failed: {str(e)}"}
    
    async def _create_vm_instance(self, vm_id: str, base_image: str, 
                                 memory_mb: int, cpu_count: int, 
                                 network_enabled: bool) -> Dict[str, Any]:
        """Create a new Firecracker VM instance"""
        vm_dir = f"/tmp/{vm_id}"
        os.makedirs(vm_dir, exist_ok=True)
        log_file = f"{vm_dir}/vm.log"
        if not os.path.exists(log_file):
            with open(log_file, 'w') as f:
                pass  

        vm_config = {
            "boot-source": {
                "kernel_image_path": self.base_images[base_image]["kernel"],
                "boot_args": "console=ttyS0 reboot=k panic=1 pci=off"
            },
            "drives": [
                {
                    "drive_id": "rootfs",
                    "path_on_host": self.base_images[base_image]["rootfs"],
                    "is_root_device": True,
                    "is_read_only": False
                }
            ],
            "machine-config": {
                "vcpu_count": cpu_count,
                "mem_size_mib": memory_mb,
                # "ht_enabled": False
                
            },
            "logger": {
                "log_path": f"{vm_dir}/vm.log",
                "level": "Info",
                "show_level": True,
                "show_log_origin": True
            }
        }
        
        if network_enabled:
            vm_config["network-interfaces"] = [
                {
                    "iface_id": "eth0", 
                    "guest_mac": "AA:FC:00:00:00:01",
                    "host_dev_name": f"tap-{vm_id}"
                }
            ]
        
        config_path = f"{vm_dir}/vm_config.json"
        with open(config_path, 'w') as f:
            json.dump(vm_config, f, indent=2)
        
        try:
            socket_path = f"{vm_dir}/firecracker.socket"
            
            process = await asyncio.create_subprocess_exec(
                self.firecracker_binary,
                "--api-sock", socket_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            await asyncio.sleep(2)
            
            api_result = await self._configure_vm_via_api(socket_path, vm_config)
            if not api_result["success"]:
                return api_result
            
            start_result = await self._start_vm_via_api(socket_path)
            if not start_result["success"]:
                return start_result
            
            self.vm_instances[vm_id] = {
                "process": process,
                "socket_path": socket_path,
                "vm_dir": vm_dir,
                "config": vm_config,
                "base_image": base_image,
                "created_at": time.time()
            }
            
            return {
                "success": True,
                "vm_id": vm_id,
                "socket_path": socket_path,
                "ssh_info": {
                    "host": "192.168.1.2",  # Default guest IP
                    "port": 22,
                    "username": "root",
                    "key_path": f"{vm_dir}/ssh_key"
                }
            }
            
        except Exception as e:
            return {"success": False, "error": f"Failed to create VM: {str(e)}"}
    
    async def _configure_vm_via_api(self, socket_path: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Configure VM using Firecracker API"""
        try:
            import requests_unixsocket
            session = requests_unixsocket.Session()
            base_url = f"http+unix://{socket_path.replace('/', '%2F')}"
            
            # Set boot source
            response = session.put(
                f"{base_url}/boot-source",
                json=config["boot-source"]
            )
            if response.status_code != 204:
                return {"success": False, "error": f"Failed to set boot source: {response.text}"}
            
            # Set drives
            for drive in config["drives"]:
                response = session.put(
                    f"{base_url}/drives/{drive['drive_id']}",
                    json=drive
                )
                if response.status_code != 204:
                    return {"success": False, "error": f"Failed to set drive: {response.text}"}
            
            # Set machine config
            response = session.put(
                f"{base_url}/machine-config",
                json=config["machine-config"]
            )
            if response.status_code != 204:
                return {"success": False, "error": f"Failed to set machine config: {response.text}"}
            
            return {"success": True}
            
        except Exception as e:
            return {"success": False, "error": f"API configuration failed: {str(e)}"}
    
    async def _start_vm_via_api(self, socket_path: str) -> Dict[str, Any]:
        """Start VM using Firecracker API"""
        try:
            import requests_unixsocket
            session = requests_unixsocket.Session()
            base_url = f"http+unix://{socket_path.replace('/', '%2F')}"
            
            # Start VM
            response = session.put(
                f"{base_url}/actions",
                json={"action_type": "InstanceStart"}
            )
            
            if response.status_code != 204:
                return {"success": False, "error": f"Failed to start VM: {response.text}"}
            
            return {"success": True}
            
        except Exception as e:
            return {"success": False, "error": f"VM start failed: {str(e)}"}
    
    async def _wait_for_vm_ready(self, vm_id: str, timeout: int = 60) -> bool:
        # TODO
        start_time = time.time()
        while time.time() - start_time < timeout:
            vm_info = self.vm_instances.get(vm_id)
            if not vm_info:
                return False
            
            socket_path = vm_info.get("socket_path")
            if not socket_path or not os.path.exists(socket_path):
                await asyncio.sleep(1)
                continue
            
            try:
                import requests_unixsocket
                session = requests_unixsocket.Session()
                base_url = f"http+unix://{socket_path.replace('/', '%2F')}"
                response = session.get(f"{base_url}/ping")
                if response.status_code == 200:
                    return True
            except Exception:
                pass
            
            await asyncio.sleep(1)
        return False

    async def _transfer_files(self, vm_id: str, files: Dict[str, str]) -> Dict[str, Any]:
        #TODO
        pass
     
    async def _execute_command_in_vm(self, vm_id: str, command: str, 
                                   env_vars: Dict[str, str] = None, 
                                   timeout: int = 60) -> Dict[str, Any]:
        # TODO
        pass
    async def _cleanup_vm(self, vm_id):
        """Safely clean up VM resources"""
        if vm_id not in self.vm_instances:
            return
        
        vm_info = self.vm_instances[vm_id]
        
        # Safely terminate process
        process = vm_info.get("process")
        if process:
            try:
                if hasattr(process, 'returncode') and process.returncode is None:
                    # Process is still running
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        try:
                            process.kill()
                            await process.wait()
                        except:
                            pass
            except ProcessLookupError:
                # Process already gone, that's fine
                pass
            except Exception:
                # Any other error during termination
                pass
        
        # Clean up socket
        socket_path = vm_info.get("socket_path")
        if socket_path and os.path.exists(socket_path):
            try:
                os.unlink(socket_path)
            except:
                pass
        
        # Remove from tracking
        try:
            del self.vm_instances[vm_id]
        except:
            pass
    
    def _select_base_image(self, execution_type: str) -> Optional[str]:
        """Select appropriate base image for execution type"""
        type_mapping = {
            "docker": "ubuntu22",
            "kubernetes": "development", 
            "web_app": "ubuntu22",
            "flutter": "development",
            "android": "development",
            "ios": "development",
            "python": "alpine",
            "node": "alpine", 
            "go": "alpine",
            "rust": "ubuntu22",
            "java": "ubuntu22",
            "custom": "ubuntu22"
        }
        
        return type_mapping.get(execution_type, "ubuntu22")
    
    async def manage_vms(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Manage VM instances"""
        operation = params.get("operation")
        vm_id = params.get("vm_id")
        
        try:
            if operation == "list":
                vm_list = []
                for vid, info in self.vm_instances.items():
                    vm_list.append({
                        "vm_id": vid,
                        "base_image": info["base_image"],
                        "created_at": info["created_at"],
                        "uptime": time.time() - info["created_at"]
                    })
                return {"vms": vm_list, "total_vms": len(vm_list)}
            
            elif operation == "stop" and vm_id:
                if vm_id in self.vm_instances:
                    await self._cleanup_vm(vm_id)
                    return {"message": f"VM {vm_id} stopped and cleaned up"}
                else:
                    return {"error": f"VM {vm_id} not found"}
            
            elif operation == "stop_all":
                stopped_vms = list(self.vm_instances.keys())
                for vid in stopped_vms:
                    await self._cleanup_vm(vid)
                return {"message": f"Stopped {len(stopped_vms)} VMs", "stopped_vms": stopped_vms}
            
            else:
                return {"error": f"Unknown operation: {operation}"}
                
        except Exception as e:
            return {"error": f"VM management failed: {str(e)}"}
    
    async def get_environment_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get information about available execution environments"""
        show_capabilities = params.get("show_capabilities", True)
        
        environments = {}
        for name, info in self.base_images.items():
            env_info = {
                "name": name,
                "description": info["description"]
            }
            
            if show_capabilities:
                env_info["capabilities"] = info["capabilities"]
            
            environments[name] = env_info
        
        return {
            "environments": environments,
            "total_environments": len(environments),
            "execution_types_supported": [
                "docker", "kubernetes", "web_app", "flutter", "android", "ios",
                "python", "node", "go", "rust", "java", "custom"
            ]
        }

# Integration with existing MCP server
def extend_mcp_server_with_firecracker(mcp_server):
    """Extend MCP server with Firecracker VM capabilities"""
    vm_manager = FirecrackerVMManager()
    vm_manager.register_tools(mcp_server)
    
    # Store reference
    mcp_server.vm_manager = vm_manager
    
    # Update execute_tool method
    original_execute_tool = mcp_server.execute_tool
    
    async def enhanced_execute_tool(tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "universal_execute":
            return await vm_manager.universal_execute(parameters)
        elif tool_name == "vm_manage":
            return await vm_manager.manage_vms(parameters)
        elif tool_name == "execution_environments":
            return await vm_manager.get_environment_info(parameters)
        else:
            return await original_execute_tool(tool_name, parameters)
    
    mcp_server.execute_tool = enhanced_execute_tool
    return mcp_server

# Example usage for different execution types
async def example_universal_execution():
    """Examples of universal execution capabilities"""
    
    # Docker example
    docker_result = await server.execute_tool("universal_execute", {
        "execution_type": "docker",
        "source_files": {
            "Dockerfile": """
FROM python:3.9-slim
COPY app.py /app.py
CMD ["python", "/app.py"]
            """,
            "app.py": "print('Hello from Docker in VM!')"
        },
        "main_command": "docker build -t myapp . && docker run myapp",
        "setup_commands": ["systemctl start docker"],
        "memory_mb": 1024,
        "network_enabled": True
    })
    
    # Kubernetes example  
    k8s_result = await server.execute_tool("universal_execute", {
        "execution_type": "kubernetes",
        "source_files": {
            "deployment.yaml": """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hello-app
spec:
  replicas: 1
  selector:
    matchLabels:
      app: hello
  template:
    metadata:
      labels:
        app: hello
    spec:
      containers:
      - name: hello
        image: nginx
        ports:
        - containerPort: 80
            """
        },
        "main_command": "kubectl apply -f deployment.yaml && kubectl get pods",
        "setup_commands": [
            "k3s server --disable=traefik &",
            "sleep 30",
            "export KUBECONFIG=/etc/rancher/k3s/k3s.yaml"
        ],
        "memory_mb": 2048,
        "timeout": 600
    })
    
    # Flutter web app example
    flutter_result = await server.execute_tool("universal_execute", {
        "execution_type": "flutter",  
        "source_files": {
            "pubspec.yaml": """
name: hello_flutter
environment:
  sdk: '>=2.17.0 <4.0.0'
dependencies:
  flutter:
    sdk: flutter
            """,
            "lib/main.dart": """
import 'package:flutter/material.dart';

void main() => runApp(MyApp());

class MyApp extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      home: Scaffold(
        body: Center(child: Text('Hello Flutter in VM!')),
      ),
    );
  }
}
            """
        },
        "main_command": "flutter build web && python -m http.server 8080 -d build/web",
        "setup_commands": [
            "flutter create . --force",
            "flutter pub get"
        ],
        "memory_mb": 2048,
        "network_enabled": True,
        "timeout": 600
    })
    
    return [docker_result, k8s_result, flutter_result]

if __name__ == "__main__":
    print("""
    Universal Execution Framework Setup:
    
    1. Install Firecracker:
       curl -LOJ https://github.com/firecracker-microvm/firecracker/releases/download/v1.4.0/firecracker-v1.4.0-x86_64.tgz
       tar -xzf firecracker-v1.4.0-x86_64.tgz
       sudo mv release-v1.4.0-x86_64/firecracker-v1.4.0-x86_64 /usr/local/bin/firecracker
    
    2. Create base VM images (Ubuntu 22.04, Alpine, Development environment)
       - This requires building custom rootfs images with your tools
    
    3. Use the framework - it can run ANYTHING!
    """)
    # test
    # Note: This is a simplified example. In a real application, you would integrate this with your MCP server.
