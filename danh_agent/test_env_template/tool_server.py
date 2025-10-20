import asyncio
import websockets
import json
import logging
import subprocess
import shutil
import os
import tempfile
import psutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
from mcp.server import Server
from mcp.types import TextContent, Tool
import aiohttp
import fnmatch

# Try to import docker, make it optional
try:
    import docker
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False
    docker = None

MCP_HOST = "0.0.0.0"
MCP_PORT = 3001
CONNECTION_MODE = "websocket"

logger = logging.getLogger(__name__)

class MCPWebSocketServer:
    """MCP Server with WebSocket support using standard websockets library"""
    
    def __init__(self):
        self.server = Server("vm-tool-server")
        self.tools = {}  # Track tools manually
        self.running_processes = {}  # Track async processes
        self.docker_client = None
        self.init_docker()
        self.setup_tools()
    
    def init_docker(self):
        """Initialize Docker client"""
        if not DOCKER_AVAILABLE:
            logger.warning("Docker library not available")
            return
            
        try:
            self.docker_client = docker.from_env()
            logger.info("Docker client initialized successfully")
        except Exception as e:
            logger.warning(f"Docker not available: {e}")
            self.docker_client = None
    
    def setup_tools(self):
        """Setup MCP tools"""
        
        @self.server.call_tool()
        async def shell_command(
            command: str,
            timeout: int = 60,
            async_execution: bool = False,
            working_directory: Optional[str] = None
        ) -> list:
            """Execute shell commands"""
            try:
                logger.info(f"Executing command: {command}")
                
                # Set working directory
                cwd = Path(working_directory) if working_directory else Path.home()
                
                if async_execution:
                    # Start process asynchronously
                    process = subprocess.Popen(
                        command,
                        shell=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        cwd=str(cwd)
                    )
                    
                    process_id = f"proc_{len(self.running_processes)}"
                    self.running_processes[process_id] = process
                    
                    result = {
                        "success": True,
                        "process_id": process_id,
                        "message": f"Command started asynchronously with ID: {process_id}",
                        "command": command,
                        "working_directory": str(cwd)
                    }
                else:
                    # Execute synchronously
                    result = subprocess.run(
                        command,
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        cwd=str(cwd)
                    )
                    
                    response = {
                        "success": result.returncode == 0,
                        "returncode": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "command": command,
                        "working_directory": str(cwd)
                    }
                    result = response
                    
            except subprocess.TimeoutExpired:
                result = {
                    "success": False,
                    "error": f"Command timed out after {timeout} seconds",
                    "command": command
                }
            except Exception as e:
                result = {
                    "success": False,
                    "error": str(e),
                    "command": command
                }
            
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        @self.server.call_tool()
        async def http_request(
            url: str,
            method: str = "GET",
            headers: Optional[Dict[str, str]] = None,
            params: Optional[Dict[str, Any]] = None,
            data: Optional[Union[Dict[str, Any], str]] = None,
            json_data: Optional[Dict[str, Any]] = None,
            timeout: int = 30,
            follow_redirects: bool = True,
            verify_ssl: bool = True
        ) -> list:
            """
            Execute HTTP requests (GET, POST, PUT, DELETE, etc.)
            
            Args:
                url: The URL to make the request to
                method: HTTP method (GET, POST, PUT, DELETE, PATCH, etc.)
                headers: Optional headers dictionary
                params: Optional query parameters dictionary
                data: Optional form data (dict or string)
                json_data: Optional JSON data dictionary
                timeout: Request timeout in seconds
                follow_redirects: Whether to follow redirects
                verify_ssl: Whether to verify SSL certificates
            """
            try:
                logger.info(f"Making {method.upper()} request to: {url}")
                
                # Prepare headers
                request_headers = headers or {}
                
                # Setup timeout
                timeout_config = aiohttp.ClientTimeout(total=timeout)
                
                # Setup SSL context
                ssl_context = None if verify_ssl else False
                
                async with aiohttp.ClientSession(
                    timeout=timeout_config,
                    connector=aiohttp.TCPConnector(ssl=ssl_context)
                ) as session:
                    
                    # Prepare request kwargs
                    request_kwargs = {
                        'url': url,
                        'headers': request_headers,
                        'params': params,
                        'allow_redirects': follow_redirects
                    }
                    
                    # Handle different data types
                    if json_data is not None:
                        request_kwargs['json'] = json_data
                        if 'content-type' not in [k.lower() for k in request_headers.keys()]:
                            request_headers['Content-Type'] = 'application/json'
                    elif data is not None:
                        if isinstance(data, dict):
                            request_kwargs['data'] = data
                        else:
                            request_kwargs['data'] = data
                    
                    # Make the request
                    async with session.request(method.upper(), **request_kwargs) as response:
                        
                        # Get response content
                        try:
                            # Try to parse as JSON first
                            response_data = await response.json()
                            content_type = "json"
                        except:
                            # Fall back to text
                            response_data = await response.text()
                            content_type = "text"
                        
                        # Prepare result
                        result = {
                            "success": 200 <= response.status < 400,
                            "status_code": response.status,
                            "status_text": response.reason,
                            "headers": dict(response.headers),
                            "content_type": content_type,
                            "data": response_data,
                            "url": str(response.url),
                            "method": method.upper(),
                            "request_headers": request_headers,
                            "request_params": params
                        }
                        
                        # Add request body info if present
                        if json_data:
                            result["request_json"] = json_data
                        elif data:
                            result["request_data"] = data
                        
                        logger.info(f"Request completed with status: {response.status}")
                        
            except asyncio.TimeoutError:
                result = {
                    "success": False,
                    "error": f"Request timed out after {timeout} seconds",
                    "url": url,
                    "method": method.upper()
                }
                logger.error(f"Request timeout: {url}")
                
            except aiohttp.ClientError as e:
                result = {
                    "success": False,
                    "error": f"Client error: {str(e)}",
                    "url": url,
                    "method": method.upper(),
                    "error_type": "ClientError"
                }
                logger.error(f"Client error for {url}: {e}")
                
            except Exception as e:
                result = {
                    "success": False,
                    "error": str(e),
                    "url": url,
                    "method": method.upper(),
                    "error_type": type(e).__name__
                }
                logger.error(f"Unexpected error for {url}: {e}")
            
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


        # Convenience methods for common HTTP operations
        @self.server.call_tool()
        async def get_request(
            url: str,
            headers: Optional[Dict[str, str]] = None,
            params: Optional[Dict[str, Any]] = None,
            timeout: int = 30
        ) -> list:
            """Convenience method for GET requests"""
            return await http_request(
                url=url,
                method="GET",
                headers=headers,
                params=params,
                timeout=timeout
            )


        @self.server.call_tool()
        async def post_request(
            url: str,
            json_data: Optional[Dict[str, Any]] = None,
            data: Optional[Union[Dict[str, Any], str]] = None,
            headers: Optional[Dict[str, str]] = None,
            timeout: int = 30
        ) -> list:
            """Convenience method for POST requests"""
            return await http_request(
                url=url,
                method="POST",
                headers=headers,
                json_data=json_data,
                data=data,
                timeout=timeout
            )


        @self.server.call_tool()
        async def put_request(
            url: str,
            json_data: Optional[Dict[str, Any]] = None,
            data: Optional[Union[Dict[str, Any], str]] = None,
            headers: Optional[Dict[str, str]] = None,
            timeout: int = 30
        ) -> list:
            """Convenience method for PUT requests"""
            return await http_request(
                url=url,
                method="PUT",
                headers=headers,
                json_data=json_data,
                data=data,
                timeout=timeout
            )


        @self.server.call_tool()
        async def delete_request(
            url: str,
            headers: Optional[Dict[str, str]] = None,
            params: Optional[Dict[str, Any]] = None,
            timeout: int = 30
        ) -> list:
            """Convenience method for DELETE requests"""
            return await http_request(
                url=url,
                method="DELETE",
                headers=headers,
                params=params,
                timeout=timeout
            )

        @self.server.call_tool()
        async def docker_container(
            image: str,
            command: str = "",
            timeout: int = 120,
            async_execution: bool = False,
            ports: Optional[Dict[str, str]] = None
        ) -> list:
            """Run Docker containers on the VM"""
            if self.docker_client is None:
                return [TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": "Docker is not available on this system"
                }, indent=2))]
            
            try:
                logger.info(f"Running Docker container: {image}")
                
                # Prepare port configuration
                port_bindings = {}
                if ports:
                    for host_port, container_port in ports.items():
                        port_bindings[container_port] = host_port
                
                if async_execution:
                    # Run container asynchronously
                    container = self.docker_client.containers.run(
                        image,
                        command=command if command else None,
                        detach=True,
                        ports=port_bindings if port_bindings else None,
                        remove=False
                    )
                    
                    result = {
                        "success": True,
                        "container_id": container.id,
                        "container_name": container.name,
                        "image": image,
                        "status": "running",
                        "ports": port_bindings
                    }
                else:
                    # Run container synchronously
                    container = self.docker_client.containers.run(
                        image,
                        command=command if command else None,
                        detach=False,
                        ports=port_bindings if port_bindings else None,
                        remove=True
                    )
                    
                    result = {
                        "success": True,
                        "output": container.decode('utf-8') if isinstance(container, bytes) else str(container),
                        "image": image,
                        "command": command,
                        "ports": port_bindings
                    }
                    
            except Exception as e:
                result = {
                    "success": False,
                    "error": str(e),
                    "image": image
                }
            
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        @self.server.call_tool()
        async def read_file(
            file_path: str,
            lines: Optional[int] = None,
            tail: Optional[int] = None,
            encoding: str = "utf-8"
        ) -> list:
            """Read files from filesystem"""
            try:
                path = Path(file_path)
                
                if not path.exists():
                    result = {
                        "success": False,
                        "error": f"File not found: {file_path}"
                    }
                else:
                    with open(path, 'r', encoding=encoding) as f:
                        if tail:
                            content_lines = f.readlines()
                            content = ''.join(content_lines[-tail:])
                        elif lines:
                            content_lines = []
                            for i, line in enumerate(f):
                                if i >= lines:
                                    break
                                content_lines.append(line)
                            content = ''.join(content_lines)
                        else:
                            content = f.read()
                    
                    result = {
                        "success": True,
                        "file_path": str(path.absolute()),
                        "content": content,
                        "size": path.stat().st_size,
                        "encoding": encoding
                    }
                    
            except Exception as e:
                result = {
                    "success": False,
                    "error": str(e),
                    "file_path": file_path
                }
            
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        @self.server.call_tool()
        async def write_file(
            file_path: str,
            content: str,
            append: bool = False,
            create_dirs: bool = True,
            backup: bool = False
        ) -> list:
            """Write content to files"""
            try:
                path = Path(file_path)
                
                if create_dirs:
                    path.parent.mkdir(parents=True, exist_ok=True)
                
                if backup and path.exists():
                    backup_path = path.with_suffix(path.suffix + '.backup')
                    shutil.copy2(path, backup_path)
                
                mode = 'a' if append else 'w'
                with open(path, mode, encoding='utf-8') as f:
                    f.write(content)
                
                result = {
                    "success": True,
                    "file_path": str(path.absolute()),
                    "mode": "append" if append else "write",
                    "size": path.stat().st_size,
                    "backup_created": backup and path.exists()
                }
                
            except Exception as e:
                result = {
                    "success": False,
                    "error": str(e),
                    "file_path": file_path
                }
            
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        @self.server.call_tool()
        async def list_directory(
            directory_path: str,
            recursive: bool = False,
            show_hidden: bool = False,
            details: bool = False,
            max_items: int = 15  # Optional limit on number of items returned
        ) -> list:
            """List contents of directories on the VM"""
            try:
                path = Path(directory_path)

                if not path.exists():
                    return [TextContent(type="text", text=json.dumps({
                        "success": False,
                        "error": f"Directory not found: {directory_path}"
                    }, indent=2))]

                if not path.is_dir():
                    return [TextContent(type="text", text=json.dumps({
                        "success": False,
                        "error": f"Path is not a directory: {directory_path}"
                    }, indent=2))]

                items = []

                if recursive:
                    pattern = "**/*" if show_hidden else "**/[!.]*"
                    for item in path.glob(pattern):
                        if not show_hidden and item.name.startswith('.'):
                            continue

                        if details:
                            stat = item.stat()
                            items.append({
                                "name": item.name,
                                "type": "directory" if item.is_dir() else "file",
                                "size": stat.st_size if item.is_file() else None
                            })
                        else:
                            items.append({
                                "name": item.name,
                                "type": "directory" if item.is_dir() else "file"
                            })

                        # Early exit if max_items is reached
                        if max_items and len(items) >= max_items:
                            break

                else:
                    dir_items = []
                    for item in path.iterdir():
                        if not show_hidden and item.name.startswith('.'):
                            continue
                        dir_items.append(item)

                    # Sort items before applying limit
                    dir_items.sort(key=lambda x: (x.is_dir(), x.name))

                    for item in dir_items:
                        if details:
                            stat = item.stat()
                            items.append({
                                "name": item.name,
                                "type": "directory" if item.is_dir() else "file",
                                "size": stat.st_size if item.is_file() else None
                            })
                        else:
                            items.append({
                                "name": item.name,
                                "type": "directory" if item.is_dir() else "file"
                            })

                        # Early exit if max_items is reached
                        if max_items and len(items) >= max_items:
                            break

                result = {
                    "success": True,
                    "directory_path": str(path.absolute()),
                    "items": items[:max_items] if max_items else items,
                    "total_items": len(items),
                    "limited": max_items is not None and len(items) > max_items
                }

            except Exception as e:
                result = {
                    "success": False,
                    "error": str(e),
                    "directory_path": directory_path
                }

            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        def is_excluded(file_path: Path, exclude_patterns: List[str]) -> bool:
            for pattern in exclude_patterns:
                if fnmatch.fnmatch(file_path.name.lower(), pattern.lower()):
                    return True
                if any(fnmatch.fnmatch(part.lower(), pattern.lower()) for part in file_path.parts):
                    return True
            return False


        @self.server.call_tool()
        async def search_files_by_pattern(
            directory_path: str,
            pattern: str = "*",
            recursive: bool = True,
            max_results: int = 50,
            exclude_patterns: Optional[List[str]] = None
        ) -> List[TextContent]:
            try:
                path = Path(directory_path)
                if not path.exists():
                    raise FileNotFoundError(f"Directory not found: {directory_path}")

                if exclude_patterns is None:
                    exclude_patterns = [
                        "__pycache__", ".git", ".svn", "node_modules", ".DS_Store"
                    ]

                results = []
                search_iter = path.rglob(pattern) if recursive else path.glob(pattern)
                count = 0

                for item in search_iter:
                    if count >= max_results:
                        break
                    if item.is_file() and not is_excluded(item, exclude_patterns):
                        results.append({
                            "name": item.name,
                            "path": str(item.absolute()),
                            "type": "file",
                            "size": item.stat().st_size
                        })
                        count += 1

                result = {
                    "success": True,
                    "search_summary": {
                        "directory": str(path.absolute()),
                        "pattern": pattern,
                        "recursive": recursive,
                        "total_found": len(results)
                    },
                    "results": results
                }

            except Exception as e:
                result = {
                    "success": False,
                    "error": str(e)
                }

            return [TextContent(type="text", text=json.dumps(result, indent=2))]


        @self.server.call_tool()
        async def search_files_by_content(
            directory_path: str,
            content_search: str,
            recursive: bool = True,
            max_results: int = 50,
            file_size_limit: int = 10 * 1024 * 1024,  # 10MB
            exclude_patterns: Optional[List[str]] = None
        ) -> List[TextContent]:
            if not content_search:
                return [TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": "content_search parameter is required and cannot be null"
                }, indent=2))]

            try:
                path = Path(directory_path)
                if not path.exists():
                    raise FileNotFoundError(f"Directory not found: {directory_path}")

                if exclude_patterns is None:
                    exclude_patterns = [
                        "*.jpg", "*.jpeg", "*.png", "*.gif", "*.bmp", "*.ico", "*.svg",
                        "*.mp4", "*.avi", "*.mov", "*.wmv", "*.flv", "*.webm",
                        "*.mp3", "*.wav", "*.flac", "*.aac", "*.ogg",
                        "*.zip", "*.rar", "*.7z", "*.tar", "*.gz", "*.bz2",
                        "*.exe", "*.dll", "*.so", "*.dylib",
                        "*.pdf", "*.doc", "*.docx", "*.xls", "*.xlsx", "*.ppt", "*.pptx",
                        "__pycache__", ".git", ".svn", "node_modules", ".DS_Store",
                        "*.pyc", "*.pyo", "*.class", "*.o", "*.obj"
                    ]

                results = []
                # Search ALL files (no pattern filter)
                search_iter = path.rglob("*") if recursive else path.glob("*")

                filtered_files = [
                    f for f in search_iter
                    if f.is_file() and not is_excluded(f, exclude_patterns)
                ]

                for item in filtered_files:
                    if len(results) >= max_results:
                        break

                    if item.stat().st_size > file_size_limit:
                        continue

                    try:
                        content = None
                        for enc in ['utf-8', 'latin1']:
                            try:
                                with open(item, 'r', encoding=enc, errors='ignore') as file:
                                    content = file.read(file_size_limit)
                                break
                            except (UnicodeDecodeError, PermissionError):
                                continue

                        if not content:
                            continue

                        search_lower = content_search.lower()
                        content_lower = content.lower()

                        if search_lower in content_lower:
                            lines = content.splitlines()
                            matches = []
                            for i, line in enumerate(lines):
                                if search_lower in line.lower():
                                    matches.append({
                                        "line_number": i + 1,
                                        "line_content": line.strip()[:200],
                                        "context_before": lines[i - 1].strip()[:100] if i > 0 else "",
                                        "context_after": lines[i + 1].strip()[:100] if i < len(lines) - 1 else ""
                                    })
                                    if len(matches) >= 3:
                                        break

                            results.append({
                                "name": item.name,
                                "path": str(item.absolute()),
                                "size": item.stat().st_size,
                                "total_matches_in_file": len(matches),
                                "matches": matches,
                                "file_preview": content[:500] + "..." if len(content) > 500 else content
                            })

                    except Exception:
                        continue

                result = {
                    "success": True,
                    "search_summary": {
                        "directory": str(path.absolute()),
                        "content_search": content_search,
                        "recursive": recursive,
                        "total_found": len(results)
                    },
                    "results": results
                }

            except Exception as e:
                result = {
                    "success": False,
                    "error": str(e)
                }

            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        @self.server.call_tool()
        async def list_processes(
            status_filter: Optional[str] = None,
            limit: int = 50
        ) -> list:
            """List running processes on the VM"""
            try:
                processes = []
                
                # Get system processes
                for proc in psutil.process_iter(['pid', 'name', 'status', 'cpu_percent', 'memory_percent', 'create_time']):
                    try:
                        proc_info = proc.info
                        if status_filter and proc_info['status'] != status_filter:
                            continue
                        
                        processes.append({
                            "pid": proc_info['pid'],
                            "name": proc_info['name'],
                            "status": proc_info['status'],
                            "cpu_percent": proc_info['cpu_percent'],
                            "memory_percent": proc_info['memory_percent'],
                            "create_time": datetime.fromtimestamp(proc_info['create_time']).isoformat()
                        })
                        
                        if len(processes) >= limit:
                            break
                            
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                
                # Add our tracked async processes
                for proc_id, proc in self.running_processes.items():
                    if proc.poll() is None:  # Still running
                        processes.append({
                            "process_id": proc_id,
                            "pid": proc.pid,
                            "name": "async_shell_command",
                            "status": "running",
                            "type": "tracked_async"
                        })
                
                result = {
                    "success": True,
                    "processes": processes,
                    "total_found": len(processes),
                    "limit": limit,
                    "status_filter": status_filter
                }
                
            except Exception as e:
                result = {
                    "success": False,
                    "error": str(e)
                }
            
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        @self.server.call_tool()
        async def get_process_logs(
            process_id: str,
            lines: int = 100
        ) -> list:
            """Get logs from a specific process on the VM"""
            try:
                if process_id not in self.running_processes:
                    return [TextContent(type="text", text=json.dumps({
                        "success": False,
                        "error": f"Process ID not found: {process_id}"
                    }, indent=2))]
                
                proc = self.running_processes[process_id]
                
                if proc.poll() is not None:
                    # Process finished, get final output
                    stdout, stderr = proc.communicate()
                    result = {
                        "success": True,
                        "process_id": process_id,
                        "status": "completed",
                        "returncode": proc.returncode,
                        "stdout": stdout,
                        "stderr": stderr
                    }
                    # Remove from tracking
                    del self.running_processes[process_id]
                else:
                    # Process still running, get partial output if available
                    result = {
                        "success": True,
                        "process_id": process_id,
                        "status": "running",
                        "message": "Process is still running. Full output available when completed."
                    }
                
            except Exception as e:
                result = {
                    "success": False,
                    "error": str(e),
                    "process_id": process_id
                }
            
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        @self.server.call_tool()
        async def create_directory(
            directory_path: str,
            parents: bool = True,
            mode: str = "755"
        ) -> list:
            """Create directories on the VM"""
            try:
                path = Path(directory_path)
                
                # Convert mode string to octal
                mode_octal = int(mode, 8)
                
                if parents:
                    path.mkdir(parents=True, exist_ok=True, mode=mode_octal)
                else:
                    path.mkdir(mode=mode_octal)
                
                result = {
                    "success": True,
                    "directory_path": str(path.absolute()),
                    "created": True,
                    "mode": mode,
                    "parents": parents
                }
                
            except FileExistsError:
                result = {
                    "success": True,
                    "directory_path": str(Path(directory_path).absolute()),
                    "created": False,
                    "message": "Directory already exists"
                }
            except Exception as e:
                result = {
                    "success": False,
                    "error": str(e),
                    "directory_path": directory_path
                }
            
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        # Manually register tools for our tracking
        self.tools = {
            "shell_command": shell_command,
            "docker_container": docker_container,
            "read_file": read_file,
            "write_file": write_file,
            "list_directory": list_directory,
            "search_files_by_pattern": search_files_by_pattern,
            "search_files_by_content": search_files_by_content,
            "list_processes": list_processes,
            "get_process_logs": get_process_logs,
            "create_directory": create_directory,
            "get_request": get_request,
            "post_request":post_request,
            "delete_request":post_request,
            "put_request":post_request
        }

    async def handle_websocket_connection(self, websocket):
        """Handle individual WebSocket connections"""
        client_address = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        logger.info(f"New WebSocket connection from {client_address}")
        
        try:
            async for message in websocket:
                try:
                    # Parse incoming JSON-RPC message
                    data = json.loads(message)
                    logger.debug(f"Received message: {data}")
                    
                    # Handle different message types
                    response = await self.handle_mcp_message(data)
                    
                    if response:
                        response_json = json.dumps(response)
                        await websocket.send(response_json)
                        logger.debug(f"Sent response: {response}")
                        
                except json.JSONDecodeError as e:
                    # Send JSON-RPC error response
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": -32700,
                            "message": "Parse error",
                            "data": str(e)
                        }
                    }
                    await websocket.send(json.dumps(error_response))
                    
                except Exception as e:
                    logger.error(f"Error handling message: {e}")
                    # Send generic error response
                    error_response = {
                        "jsonrpc": "2.0", 
                        "id": data.get("id") if isinstance(data, dict) else None,
                        "error": {
                            "code": -32603,
                            "message": "Internal error",
                            "data": str(e)
                        }
                    }
                    await websocket.send(json.dumps(error_response))
                    
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"WebSocket connection closed: {client_address}")
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")

    async def handle_mcp_message(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle MCP protocol messages"""
        
        if not isinstance(data, dict) or data.get("jsonrpc") != "2.0":
            return {
                "jsonrpc": "2.0",
                "id": data.get("id"),
                "error": {
                    "code": -32600,
                    "message": "Invalid Request"
                }
            }
        
        method = data.get("method")
        message_id = data.get("id")
        params = data.get("params", {})
        
        try:
            if method == "initialize":
                # Handle initialization
                return {
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {}
                        },
                        "serverInfo": {
                            "name": "vm-tool-server",
                            "version": "1.0.0"
                        }
                    }
                }
                
            elif method == "tools/list":
                # Return available tools using our manual tracking
                tools = []
                for tool_name, tool_func in self.tools.items():
                    # Get tool schema from function signature and docstring
                    import inspect
                    sig = inspect.signature(tool_func)
                    
                    properties = {}
                    required = []
                    
                    for param_name, param in sig.parameters.items():
                        if param_name in ['self']:
                            continue
                            
                        param_info = {
                            "type": "string"  # Default to string, could be enhanced
                        }
                        
                        # Check if parameter has a default value
                        if param.default == inspect.Parameter.empty:
                            required.append(param_name)
                        else:
                            param_info["default"] = param.default
                        
                        # Add type hints if available
                        if param.annotation != inspect.Parameter.empty:
                            if param.annotation == int:
                                param_info["type"] = "integer"
                            elif param.annotation == bool:
                                param_info["type"] = "boolean"
                            elif param.annotation == float:
                                param_info["type"] = "number"
                        
                        properties[param_name] = param_info
                    
                    tools.append({
                        "name": tool_name,
                        "description": tool_func.__doc__ or f"Tool: {tool_name}",
                        "inputSchema": {
                            "type": "object",
                            "properties": properties,
                            "required": required
                        }
                    })
                
                return {
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "result": {
                        "tools": tools
                    }
                }
                
            elif method == "tools/call":
                # Call a tool
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                
                if tool_name not in self.tools:
                    return {
                        "jsonrpc": "2.0",
                        "id": message_id,
                        "error": {
                            "code": -32601,
                            "message": f"Tool not found: {tool_name}"
                        }
                    }
                
                # Execute the tool
                tool_func = self.tools[tool_name]
                try:
                    result = await tool_func(**arguments)
                    
                    # Convert result to proper format
                    if isinstance(result, list):
                        tool_result = [{"type": item.type, "text": item.text} for item in result]
                    else:
                        tool_result = [{"type": "text", "text": str(result)}]
                    
                    return {
                        "jsonrpc": "2.0",
                        "id": message_id,
                        "result": tool_result
                    }
                    
                except Exception as e:
                    logger.error(f"Tool execution error: {e}")
                    return {
                        "jsonrpc": "2.0",
                        "id": message_id,
                        "error": {
                            "code": -32603,
                            "message": f"Tool execution failed: {str(e)}"
                        }
                    }
                    
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}"
                    }
                }
                
        except Exception as e:
            logger.error(f"Error handling MCP message: {e}")
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "error": {
                    "code": -32603,
                    "message": "Internal error",
                    "data": str(e)
                }
            }

    async def start_server(self):
        """Start the WebSocket server"""
        if CONNECTION_MODE == "websocket":
            logger.info(f"Starting MCP Tool Server (websocket mode) on {MCP_HOST}:{MCP_PORT}...")
            
            # Start WebSocket server using standard websockets library
            async with websockets.serve(
                self.handle_websocket_connection,
                host=MCP_HOST,
                port=MCP_PORT,
                ping_interval=20,
                ping_timeout=10,
                max_size=1024*1024,  # 1MB max message size
                max_queue=32
            ) as ws_server:
                logger.info(f"MCP WebSocket server started on ws://{MCP_HOST}:{MCP_PORT}")
                logger.info("Server is ready to accept connections...")
                
                # Keep the server running
                try:
                    await ws_server.wait_closed()
                except KeyboardInterrupt:
                    logger.info("Server shutdown requested")
                except Exception as e:
                    logger.error(f"Server error: {e}")

# Test client for debugging
async def test_client():
    """Simple test client to verify the server works"""
    uri = f"ws://{MCP_HOST}:{MCP_PORT}"
    
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected to MCP server")
            
            # Test initialization
            init_message = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "test-client",
                        "version": "1.0.0"
                    }
                }
            }
            
            await websocket.send(json.dumps(init_message))
            response = await websocket.recv()
            print("Initialize response:", json.loads(response))
            
            # Test tools list
            tools_message = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {}
            }
            
            await websocket.send(json.dumps(tools_message))
            response = await websocket.recv()
            tools_response = json.loads(response)
            print(f"Available tools: {len(tools_response['result']['tools'])}")
            for tool in tools_response['result']['tools']:
                print(f"  - {tool['name']}: {tool['description']}")
            
            # Test tool call
            tool_message = {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "shell_command",
                    "arguments": {
                        "command": "echo 'Hello from MCP!'"
                    }
                }
            }
            
            await websocket.send(json.dumps(tool_message))
            response = await websocket.recv()
            print("Tool response:", json.loads(response))
            
    except Exception as e:
        print(f"Test failed: {e}")

# Usage
async def main():
    """Main function"""
    server = MCPWebSocketServer()
    await server.start_server()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Uncomment to run test client instead of server
    # asyncio.run(test_client())
    
    # Run server
    asyncio.run(main())