#!/usr/bin/env python3
"""
MCP Sandbox Server - Provides VM sandbox capabilities to LLM agents
"""

import asyncio
import json
import subprocess
import shlex
import os
import tempfile
import logging
from typing import Any, Sequence, Dict, Optional, List
from pathlib import Path
import aiofiles

from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
    LoggingLevel
)
import mcp.types as types

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-sandbox")

class VMSandbox:
    def __init__(self):
        self.vm_name = "mcp-sandbox"
        self.vm_running = False
        self.setup_complete = False
        
    async def ensure_vm_exists(self) -> bool:
        """Ensure the sandbox VM exists and is configured"""
        try:
            # Check if VM exists
            result = await self._run_command(["multipass", "list", "--format", "json"])
            if result["return_code"] != 0:
                return False
                
            vms = json.loads(result["stdout"])
            vm_exists = any(vm["name"] == self.vm_name for vm in vms.get("list", []))
            
            if not vm_exists:
                logger.info("Creating new sandbox VM...")
                await self._create_vm()
                
            return True
        except Exception as e:
            logger.error(f"Error ensuring VM exists: {e}")
            return False
    
    async def _create_vm(self):
        """Create a new sandbox VM with MCP tools pre-installed"""
        cloud_init = """#cloud-config
package_update: true
packages:
  - python3-pip
  - python3-venv
  - docker.io
  - curl
  - jq
  - git
  - vim
  - htop
  - build-essential

users:
  - name: ubuntu
    groups: [docker, sudo]
    shell: /bin/bash

runcmd:
  - 'usermod -aG docker ubuntu'
  - 'systemctl enable --now docker'
  - 'sudo -u ubuntu python3 -m venv /home/ubuntu/mcp_env'
  - 'sudo -u ubuntu /home/ubuntu/mcp_env/bin/pip install --upgrade pip'
  - 'chown -R ubuntu:ubuntu /home/ubuntu'
"""
        
        # Write cloud-init to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(cloud_init)
            cloud_init_path = f.name
        
        try:
            # Create VM with cloud-init
            cmd = [
                "multipass", "launch", "22.04",
                "--name", self.vm_name,
                "--cpus", "2",
                "--memory", "4G", 
                "--disk", "20G",
                "--cloud-init", cloud_init_path
            ]
            
            result = await self._run_command(cmd, timeout=300)
            if result["return_code"] != 0:
                raise Exception(f"Failed to create VM: {result['stderr']}")
                
            logger.info("VM created successfully")
            
            # Wait for cloud-init to complete
            await asyncio.sleep(30)
            self.setup_complete = True
            
        finally:
            os.unlink(cloud_init_path)
    
    async def start_vm(self) -> Dict[str, Any]:
        """Start the sandbox VM"""
        if not await self.ensure_vm_exists():
            return {"success": False, "error": "Failed to ensure VM exists"}
            
        try:
            result = await self._run_command(["multipass", "start", self.vm_name])
            if result["return_code"] == 0:
                self.vm_running = True
                # Get VM info
                info_result = await self._run_command(["multipass", "info", self.vm_name, "--format", "json"])
                if info_result["return_code"] == 0:
                    vm_info = json.loads(info_result["stdout"])
                    return {
                        "success": True,
                        "vm_info": vm_info,
                        "message": "VM started successfully"
                    }
            return {"success": False, "error": result["stderr"]}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def stop_vm(self) -> Dict[str, Any]:
        """Stop the sandbox VM"""
        try:
            result = await self._run_command(["multipass", "stop", self.vm_name])
            if result["return_code"] == 0:
                self.vm_running = False
                return {"success": True, "message": "VM stopped successfully"}
            return {"success": False, "error": result["stderr"]}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def execute_command(self, command: str, timeout: int = 120) -> Dict[str, Any]:
        """Execute a command in the sandbox VM"""
        if not self.vm_running:
            start_result = await self.start_vm()
            if not start_result["success"]:
                return start_result
        
        try:
            # Use multipass exec to run command in VM
            cmd = ["multipass", "exec", self.vm_name, "--"] + shlex.split(command)
            result = await self._run_command(cmd, timeout=timeout)
            
            return {
                "success": True,
                "stdout": result["stdout"],
                "stderr": result["stderr"],
                "return_code": result["return_code"],
                "command": command
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def upload_file(self, local_path: str, remote_path: str) -> Dict[str, Any]:
        """Upload a file to the sandbox VM"""
        try:
            cmd = ["multipass", "transfer", local_path, f"{self.vm_name}:{remote_path}"]
            result = await self._run_command(cmd)
            
            if result["return_code"] == 0:
                return {"success": True, "message": f"File uploaded to {remote_path}"}
            return {"success": False, "error": result["stderr"]}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def download_file(self, remote_path: str, local_path: str) -> Dict[str, Any]:
        """Download a file from the sandbox VM"""
        try:
            cmd = ["multipass", "transfer", f"{self.vm_name}:{remote_path}", local_path]
            result = await self._run_command(cmd)
            
            if result["return_code"] == 0:
                return {"success": True, "message": f"File downloaded to {local_path}"}
            return {"success": False, "error": result["stderr"]}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def create_snapshot(self, snapshot_name: str) -> Dict[str, Any]:
        """Create a snapshot of the VM"""
        try:
            cmd = ["multipass", "snapshot", self.vm_name, "--name", snapshot_name]
            result = await self._run_command(cmd)
            
            if result["return_code"] == 0:
                return {"success": True, "message": f"Snapshot '{snapshot_name}' created"}
            return {"success": False, "error": result["stderr"]}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def restore_snapshot(self, snapshot_name: str) -> Dict[str, Any]:
        """Restore VM from a snapshot"""
        try:
            cmd = ["multipass", "restore", f"{self.vm_name}.{snapshot_name}"]
            result = await self._run_command(cmd)
            
            if result["return_code"] == 0:
                return {"success": True, "message": f"Restored from snapshot '{snapshot_name}'"}
            return {"success": False, "error": result["stderr"]}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_vm_info(self) -> Dict[str, Any]:
        """Get detailed VM information"""
        try:
            cmd = ["multipass", "info", self.vm_name, "--format", "json"]
            result = await self._run_command(cmd)
            
            if result["return_code"] == 0:
                return {"success": True, "info": json.loads(result["stdout"])}
            return {"success": False, "error": result["stderr"]}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _run_command(self, cmd: List[str], timeout: int = 60) -> Dict[str, Any]:
        """Run a command asynchronously"""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), 
                timeout=timeout
            )
            
            return {
                "stdout": stdout.decode('utf-8', errors='replace'),
                "stderr": stderr.decode('utf-8', errors='replace'),
                "return_code": process.returncode
            }
        except asyncio.TimeoutError:
            process.kill()
            return {
                "stdout": "",
                "stderr": f"Command timed out after {timeout} seconds",
                "return_code": -1
            }
        except Exception as e:
            return {
                "stdout": "",
                "stderr": str(e),
                "return_code": -1
            }

# Initialize sandbox
sandbox = VMSandbox()

# Create MCP server
server = Server("mcp-sandbox")

@server.list_tools()
async def handle_list_tools() -> List[Tool]:
    """List available sandbox tools"""
    return [
        Tool(
            name="start_sandbox",
            description="Start the sandbox VM",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="stop_sandbox", 
            description="Stop the sandbox VM",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="execute_command",
            description="Execute a shell command in the sandbox VM",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute"
                    },
                    "timeout": {
                        "type": "integer", 
                        "description": "Command timeout in seconds",
                        "default": 120
                    }
                },
                "required": ["command"]
            }
        ),
        Tool(
            name="upload_file",
            description="Upload a file to the sandbox VM",
            inputSchema={
                "type": "object",
                "properties": {
                    "local_path": {
                        "type": "string",
                        "description": "Local file path"
                    },
                    "remote_path": {
                        "type": "string", 
                        "description": "Remote path in VM"
                    }
                },
                "required": ["local_path", "remote_path"]
            }
        ),
        Tool(
            name="download_file",
            description="Download a file from the sandbox VM",
            inputSchema={
                "type": "object",
                "properties": {
                    "remote_path": {
                        "type": "string",
                        "description": "Remote file path in VM"
                    },
                    "local_path": {
                        "type": "string",
                        "description": "Local destination path"
                    }
                },
                "required": ["remote_path", "local_path"]
            }
        ),
        Tool(
            name="create_snapshot",
            description="Create a snapshot of the current VM state",
            inputSchema={
                "type": "object",
                "properties": {
                    "snapshot_name": {
                        "type": "string",
                        "description": "Name for the snapshot"
                    }
                },
                "required": ["snapshot_name"]
            }
        ),
        Tool(
            name="restore_snapshot",
            description="Restore VM from a snapshot",
            inputSchema={
                "type": "object",
                "properties": {
                    "snapshot_name": {
                        "type": "string",
                        "description": "Name of the snapshot to restore"
                    }
                },
                "required": ["snapshot_name"]
            }
        ),
        Tool(
            name="get_vm_info",
            description="Get detailed information about the sandbox VM",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="run_python_code",
            description="Run Python code in the sandbox VM",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Execution timeout in seconds",
                        "default": 120
                    }
                },
                "required": ["code"]
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
    """Handle tool calls"""
    
    if name == "start_sandbox":
        result = await sandbox.start_vm()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "stop_sandbox":
        result = await sandbox.stop_vm()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "execute_command":
        command = arguments.get("command", "")
        timeout = arguments.get("timeout", 120)
        result = await sandbox.execute_command(command, timeout)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "upload_file":
        local_path = arguments.get("local_path", "")
        remote_path = arguments.get("remote_path", "")
        result = await sandbox.upload_file(local_path, remote_path)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "download_file":
        remote_path = arguments.get("remote_path", "")
        local_path = arguments.get("local_path", "")
        result = await sandbox.download_file(remote_path, local_path)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "create_snapshot":
        snapshot_name = arguments.get("snapshot_name", "")
        result = await sandbox.create_snapshot(snapshot_name)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "restore_snapshot":
        snapshot_name = arguments.get("snapshot_name", "")
        result = await sandbox.restore_snapshot(snapshot_name)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "get_vm_info":
        result = await sandbox.get_vm_info()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "run_python_code":
        code = arguments.get("code", "")
        timeout = arguments.get("timeout", 120)
        
        # Create a temporary Python file and execute it
        python_command = f'python3 -c "{code.replace(chr(34), chr(92)+chr(34))}"'
        result = await sandbox.execute_command(python_command, timeout)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    
    else:
        raise ValueError(f"Unknown tool: {name}")

async def main():
    # Run the server using stdin/stdout streams
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="mcp-sandbox",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    asyncio.run(main())