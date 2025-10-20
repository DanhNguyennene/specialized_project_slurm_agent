#!/usr/bin/env python3
"""
Log Streaming Service Backend
Monitors and streams logs from VM and process levels in real-time
Integrates with MultipassController to access VM logs
"""

import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Optional
import aiofiles
import aiohttp
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import uvicorn
from pydantic import BaseModel
from contextlib import asynccontextmanager
import threading
LOG_DIR = os.environ.get("LOG_DIR", "/home/danhvuive/vm_logs")
MULTIPASS_CONTROLLER_IP = os.environ.get("MULTIPASS_CONTROLLER_IP", "localhost")
MULTIPASS_CONTROLLER_PORT = os.environ.get("MULTIPASS_CONTROLLER_PORT", "8010")
class LogEntry(BaseModel):
    timestamp: str
    level: str  # "vm" or "process"
    source: str  # file path
    content: str
    file_size: int

class LogFileInfo(BaseModel):
    path: str
    name: str
    size: int
    modified: str
    level: str  # "vm" or "process"
    agent_id: Optional[str] = None
    vm_name: Optional[str] = None

class LogStreamingService:
    def __init__(self, 
                 vm_logs_dir: str = LOG_DIR,
                 MULTIPASS_CONTROLLER_IP: str = f'http://{MULTIPASS_CONTROLLER_IP}:{MULTIPASS_CONTROLLER_PORT}'):
        self.vm_logs_dir = Path(vm_logs_dir)
        self.MULTIPASS_CONTROLLER_IP = MULTIPASS_CONTROLLER_IP
        self.active_connections: Set[WebSocket] = set()
        self.file_positions: Dict[str, int] = {}  # Track file read positions
        self.observers: List[Observer] = []
        self.vm_process_logs: Dict[str, Dict] = {}  # Cache VM process logs
        self.loop = None  # Store the main event loop
        
        # Ensure host VM logs directory exists
        self.vm_logs_dir.mkdir(parents=True, exist_ok=True)
        
        # Start periodic VM log checking
        self.vm_log_check_task = None
    
    def set_event_loop(self, loop):
        """Set the event loop for async operations from threads"""
        self.loop = loop
    
    def _setup_host_watchers(self):
        """Setup file system watchers for host VM logs directory"""
        vm_handler = LogFileHandler(self, "vm")
        
        # VM logs observer for host directory
        vm_observer = Observer()
        vm_observer.schedule(vm_handler, str(self.vm_logs_dir), recursive=True)
        self.observers.append(vm_observer)
        
        # Start observers
        for observer in self.observers:
            observer.start()
        
        print(f"Started watching host VM logs: {self.vm_logs_dir}")
    
    async def start_vm_log_monitoring(self):
        """Start monitoring VM process logs"""
        # Store the current event loop
        self.loop = asyncio.get_event_loop()
        
        # Setup file watchers after event loop is available
        self._setup_host_watchers()
        
        self.vm_log_check_task = asyncio.create_task(self._vm_log_monitor_loop())
        print("Started VM process log monitoring")
    
    async def stop_vm_log_monitoring(self):
        """Stop monitoring VM process logs"""
        if self.vm_log_check_task:
            self.vm_log_check_task.cancel()
            try:
                await self.vm_log_check_task
            except asyncio.CancelledError:
                pass
        print("Stopped VM process log monitoring")
    
    async def _vm_log_monitor_loop(self):
        """Periodically check VM process logs"""
        while True:
            try:
                await self._check_vm_process_logs()
                await asyncio.sleep(2)  # Check every 2 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in VM log monitor: {e}")
                await asyncio.sleep(5)
    
    async def _check_vm_process_logs(self):
        """Check for updates in VM process logs"""
        try:
            # Get VM status from multipass controller
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.MULTIPASS_CONTROLLER_IP}/vm_status") as response:
                    if response.status == 200:
                        vm_status_data = await response.json()
                        vm_status = vm_status_data.get("data", {})
                        
                        # Check each VM for process updates
                        for vm_name, vm_info in vm_status.items():
                            agent_id = vm_info.get("assigned_agent")
                            if agent_id:
                                await self._check_vm_processes(agent_id, vm_name)
        except Exception as e:
            print(f"Error checking VM process logs: {e}")
    
    async def _check_vm_processes(self, agent_id: str, vm_name: str):
        """Check processes for a specific VM"""
        try:
            async with aiohttp.ClientSession() as session:
                # Pull logs first
                async with session.get(f"{self.MULTIPASS_CONTROLLER_IP}/pull_logs/{agent_id}/{vm_name}") as pull_response:
                    if pull_response.status != 200:
                        print(f"Failed to pull logs for VM {vm_name}: {await pull_response.text()}")
                        return
                
                # Check the transferred log directory
                log_dir = os.path.join(LOG_DIR,agent_id, vm_name)
                
                if os.path.exists(log_dir):
                    for root, dirs, filenames in os.walk(log_dir):
                        for filename in filenames:
                            if filename.endswith('.log'):
                                file_path = os.path.join(root, filename)
                                
                                # Check if file has been updated
                                cache_key = f"{agent_id}:{vm_name}:{filename}"
                                cached_info = self.vm_process_logs.get(cache_key, {})
                                
                                current_mtime = os.path.getmtime(file_path)
                                last_mtime = cached_info.get("mtime", 0)
                                
                                if current_mtime > last_mtime:
                                    # File has been updated, broadcast the change
                                    relative_path = os.path.relpath(file_path, log_dir)
                                    virtual_path = os.path.join(LOG_DIR, agent_id, vm_name, relative_path)

                                    await self.broadcast_log_update(
                                        virtual_path,
                                        "process",
                                        "modified",
                                        content="",  # Will be loaded on demand
                                        file_info={
                                            "path": virtual_path,
                                            "name": filename,
                                            "size": os.path.getsize(file_path),
                                            "modified": datetime.fromtimestamp(current_mtime).isoformat(),
                                            "level": "process",
                                            "agent_id": agent_id,
                                            "vm_name": vm_name
                                        }
                                    )
                                    
                                    # Update cache
                                    self.vm_process_logs[cache_key] = {
                                        "mtime": current_mtime,
                                        "last_updated": datetime.now().isoformat()
                                    }
                                    
        except Exception as e:
            print(f"Error checking VM processes for {vm_name}: {e}")
    
    def schedule_broadcast(self, *args, **kwargs):
        """Schedule a broadcast from a thread-safe context"""
        if self.loop and not self.loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                self.broadcast_log_update(*args, **kwargs), 
                self.loop
            )
    
    async def add_connection(self, websocket: WebSocket):
        """Add a new WebSocket connection"""
        await websocket.accept()
        self.active_connections.add(websocket)
        print(f"New connection added. Total: {len(self.active_connections)}")
        
        # Send current log files to new connection
        await self._send_initial_data(websocket)
    
    def remove_connection(self, websocket: WebSocket):
        """Remove a WebSocket connection"""
        self.active_connections.discard(websocket)
        print(f"Connection removed. Total: {len(self.active_connections)}")
    
    async def _send_initial_data(self, websocket: WebSocket):
        """Send initial log file list to new connection"""
        try:
            log_files = await self.get_log_files()
            await websocket.send_json({
                "type": "initial_files",
                "files": [file.model_dump() for file in log_files]  # Fixed: use model_dump instead of dict
            })
        except Exception as e:
            print(f"Error sending initial data: {e}")
    
    async def broadcast_log_update(self, file_path: str, level: str, event_type: str, 
                                 content: str = "", file_info: dict = None):
        """Broadcast log updates to all connected clients"""
        if not self.active_connections:
            return
        
        try:
            # For host files, read content if not provided
            if not content and level == "vm" and os.path.exists(file_path):
                content = await self._read_new_content(file_path)
            
            if content or event_type in ["created", "deleted", "moved"]:
                message = {
                    "type": "log_update",
                    "event": event_type,
                    "level": level,
                    "file_path": file_path,
                    "timestamp": datetime.now().isoformat(),
                    "content": content,
                    "file_info": file_info or (self._get_file_info(file_path, level) if os.path.exists(file_path) else None)
                }
                
                # Send to all connections
                disconnected = set()
                for websocket in self.active_connections:
                    try:
                        await websocket.send_json(message)
                    except Exception as e:
                        print(f"Error sending to websocket: {e}")
                        disconnected.add(websocket)
                
                # Remove disconnected websockets
                for websocket in disconnected:
                    self.active_connections.discard(websocket)
                    
        except Exception as e:
            print(f"Error broadcasting update: {e}")
    
    def _get_file_info(self, file_path: str, level: str) -> dict:
        """Get file information for a given path"""
        try:
            if os.path.exists(file_path):
                stat = os.stat(file_path)
                return {
                    "path": file_path,
                    "name": os.path.basename(file_path),
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "level": level
                }
        except Exception as e:
            print(f"Error getting file info for {file_path}: {e}")
        return None
    
    async def _read_new_content(self, file_path: str) -> str:
        """Read new content from file since last read"""
        try:
            if not os.path.exists(file_path):
                return ""
            
            current_position = self.file_positions.get(file_path, 0)
            
            async with aiofiles.open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                await f.seek(current_position)
                new_content = await f.read()
                self.file_positions[file_path] = await f.tell()
                
            return new_content
        except Exception as e:
            print(f"Error reading file {file_path}: {e}")
            return ""
    
    async def get_log_files(self) -> List[LogFileInfo]:
        """Get list of all log files (host + VM processes)"""
        files = []
        
        # Host VM log files
        try:
            for file_path in self.vm_logs_dir.glob("*/*.log"):
                vm_name = str(file_path).split('/')[-1].split('_')[0]
                agent_id = str(file_path).split('/')[-2]
                if file_path.is_file():
                    stat = file_path.stat()
                    files.append(LogFileInfo(
                        path=str(file_path),
                        name=file_path.name,
                        size=stat.st_size,
                        modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        level="vm",
                        agent_id=agent_id,
                        vm_name=vm_name,
                    ))
        except Exception as e:
            print(f"Error scanning VM logs: {e}")
        
        # VM Process log files (transfer from VM and scan local directory)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.MULTIPASS_CONTROLLER_IP}/vm_status") as response:
                    if response.status == 200:
                        vm_status_data = await response.json()
                        vm_status = vm_status_data.get("data", {})
                        
                        for vm_name, vm_info in vm_status.items():
                            agent_id = vm_info.get("assigned_agent")
                            if agent_id:
                                try:
                                    # Transfer logs from VM to host via API
                                    async with session.get(f"{self.MULTIPASS_CONTROLLER_IP}/pull_logs/{agent_id}/{vm_name}") as pull_response:
                                        if pull_response.status != 200:
                                            print(f"Failed to pull logs for VM {vm_name}: {await pull_response.text()}")
                                            continue
                                    
                                    # Scan the transferred log directory
                                    log_dir = os.path.join(LOG_DIR,agent_id, vm_name)
                                    
                                    if os.path.exists(log_dir):
                                        for root, dirs, filenames in os.walk(log_dir):
                                            for filename in filenames:
                                                if filename.endswith('.log'):
                                                    file_path = os.path.join(root, filename)
                                                    stat_info = os.stat(file_path)
                                                    
                                                    # Create relative path for virtual_path
                                                    relative_path = os.path.relpath(file_path, log_dir)
                                                    virtual_path = os.path.join(LOG_DIR, agent_id, vm_name, relative_path)
                                                    files.append(LogFileInfo(
                                                        path=virtual_path,
                                                        name=filename,
                                                        size=stat_info.st_size,
                                                        modified=datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
                                                        level="process",
                                                        agent_id=agent_id,
                                                        vm_name=vm_name
                                                    ))
                                                    
                                except Exception as e:
                                    print(f"Error transferring logs for VM {vm_name}: {str(e)}")
                                    
        except Exception as e:
            print(f"Error getting VM process logs: {e}")
        
        return sorted(files, key=lambda x: x.modified, reverse=True)
    
    async def get_file_content(self, file_path: str, lines: int = 100) -> str:
        """Get content from a log file"""
        try:
            # Check if it's a VM process log (virtual path)
            if file_path.startswith("/vm_processes/"):
                return await self._get_vm_process_content(file_path, lines)
            
            # Host file
            async with aiofiles.open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = await f.read()
                
            # Return last N lines if requested
            if lines > 0:
                lines_list = content.split('\n')
                if len(lines_list) > lines:
                    return '\n'.join(lines_list[-lines:])
            
            return content
        except Exception as e:
            print(f"Error reading file {file_path}: {e}")
            return f"Error reading file: {str(e)}"
    
    async def _get_vm_process_content(self, virtual_path: str, lines: int = 100) -> str:
        """Get content from VM process logs"""
        try:
            # Parse virtual path: /vm_processes/{agent_id}/{vm_name}/{relative_path}
            path_parts = virtual_path.strip('/').split('/')
            if len(path_parts) >= 4:
                agent_id = path_parts[1]
                vm_name = path_parts[2]
                relative_path = '/'.join(path_parts[3:])
                
                # Try to read from local transferred file first
                local_file_path = os.path.join(LOG_DIR,agent_id,vm_name,relative_path)
                if os.path.exists(local_file_path):
                    async with aiofiles.open(local_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = await f.read()
                        
                    # Return last N lines if requested
                    if lines > 0:
                        lines_list = content.split('\n')
                        if len(lines_list) > lines:
                            return '\n'.join(lines_list[-lines:])
                    
                    return content
                else:
                    return f"File not found: {local_file_path}"
            
            return "Invalid virtual path format"
        except Exception as e:
            return f"Error fetching VM process logs: {str(e)}"
    
    def cleanup(self):
        """Cleanup resources"""
        for observer in self.observers:
            observer.stop()
            observer.join()
        print("Log streaming service cleanup completed")

class LogFileHandler(FileSystemEventHandler):
    """Handler for file system events"""
    
    def __init__(self, service: LogStreamingService, level: str):
        self.service = service
        self.level = level
    
    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.log'):
            self.service.schedule_broadcast(
                event.src_path, self.level, "modified"
            )
    
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.log'):
            self.service.schedule_broadcast(
                event.src_path, self.level, "created"
            )
    
    def on_deleted(self, event):
        if not event.is_directory and event.src_path.endswith('.log'):
            self.service.schedule_broadcast(
                event.src_path, self.level, "deleted"
            )

# FastAPI application with lifespan events
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await log_service.start_vm_log_monitoring()
    yield
    # Shutdown
    await log_service.stop_vm_log_monitoring()
    log_service.cleanup()

app = FastAPI(title="Log Streaming Service", version="1.0.0", lifespan=lifespan)

# Global service instance
log_service = LogStreamingService()

# Serve static files (frontend)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def serve_index():
    """Serve the main frontend page"""
    return FileResponse("static/index.html")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time log streaming"""
    await log_service.add_connection(websocket)
    
    try:
        while True:
            # Keep connection alive and handle client messages
            message = await websocket.receive_text()
            data = json.loads(message)
            
            if data.get("type") == "get_file_content":
                file_path = data.get("file_path")
                lines = data.get("lines", 100)
                
                if file_path:
                    content = await log_service.get_file_content(file_path, lines)
                    await websocket.send_json({
                        "type": "file_content",
                        "file_path": file_path,
                        "content": content
                    })
    
    except WebSocketDisconnect:
        log_service.remove_connection(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        log_service.remove_connection(websocket)

@app.get("/api/files")
async def get_log_files():
    """Get list of all log files"""
    files = await log_service.get_log_files()
    return {"files": [file.model_dump() for file in files]}  # Fixed: use model_dump instead of dict

@app.get("/api/file-content")
async def get_file_content(file_path: str, lines: int = 100):
    """Get content of a specific log file"""
    content = await log_service.get_file_content(file_path, lines)
    return {
        "file_path": file_path,
        "content": content,
        "lines": lines
    }

# if __name__ == "__main__":
#     try:
#         uvicorn.run(
#             app, 
#             host="0.0.0.0", 
#             port=8080,
#             log_level="info"
#         )
#     except KeyboardInterrupt:
#         print("\nShutting down log streaming service...")
#         log_service.cleanup()
#     except Exception as e:
#         print(f"Error starting server: {e}")
#         log_service.cleanup()