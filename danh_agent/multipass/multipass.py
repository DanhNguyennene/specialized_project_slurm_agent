import subprocess
import asyncio
import json
import logging
import threading
import time
import os
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from haikunator import Haikunator
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import aiofiles
from queue import Queue, Empty

from os import environ


LOG_DIR = environ.get("LOG_DIR", "/home/danhvuive/vm_logs")
MCP_STARTUP_TIME = 25   # seconds to wait for MCP server to start
MCP_POSTSTARTUP_TIME = 5  # seconds to wait for MCP server to start

import os
import re
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List

class VMStatus(Enum):
    READY = "ready"
    BUSY = "busy"
    ERROR = "error"
    STARTING = "starting"
    STOPPED = "stopped"
    ILDE = "idle"

class CommandResult:
    def __init__(self):
        self.timestamp = None
        self.command = None
        self.process_id = None
        self.status = None
        self.exit_code = None
        self.error_message = None
        self.output_lines = []

def parse_command_block(lines: List[str], start_idx: int) -> Optional[CommandResult]:
    """Parse a command execution block from log lines"""
    result = CommandResult()
    i = start_idx
    
    # Parse starting command line
    start_match = re.match(r'\[([^\]]+)\] Starting command: (.+)', lines[i])
    if not start_match:
        return None
    
    result.timestamp = start_match.group(1)
    result.command = start_match.group(2)
    i += 1
    
    # Parse process ID
    if i < len(lines):
        pid_match = re.match(r'\[([^\]]+)\] Process ID: (.+)', lines[i])
        if pid_match:
            result.process_id = pid_match.group(2)
            i += 1
    
    # Skip separator line
    if i < len(lines) and '=' in lines[i]:
        i += 1
    
    # Parse command output/error lines
    while i < len(lines) and not lines[i].strip().startswith('='):
        line = lines[i].strip()
        if line and not line.startswith('['):
            result.output_lines.append(line)
        elif line.startswith('[') and ('Command finished' in line or 'Status:' in line or 'Exit code:' in line):
            break
        i += 1
    
    # Skip separator line
    if i < len(lines) and '=' in lines[i]:
        i += 1
    
    # Parse command finished, status, and exit code
    while i < len(lines):
        line = lines[i].strip()
        if '[' in line and '] Command finished' in line:
            pass  # Already have timestamp
        elif '[' in line and '] Status: ' in line:
            status_match = re.search(r'Status: (.+)', line)
            if status_match:
                result.status = status_match.group(1)
        elif '[' in line and '] Exit code: ' in line:
            exit_match = re.search(r'Exit code: (\d+)', line)
            if exit_match:
                result.exit_code = int(exit_match.group(1))
        elif '[' in line and '] Log writer stopping' in line:
            break
        elif not line.startswith('['):
            # Additional output lines
            if line:
                result.output_lines.append(line)
        i += 1
        
        # Break if we hit the next command or end
        if i >= len(lines) or (lines[i].strip().startswith('[') and 'Starting command:' in lines[i]):
            break
    
    # Set error message from output if command failed
    if result.status == 'failed' and result.output_lines:
        result.error_message = ' '.join(result.output_lines)
    
    return result

def determine_vm_status_from_command(cmd_result: CommandResult) -> VMStatus:
    """Determine VM status based on command execution result"""
    if not cmd_result:
        return VMStatus.BUSY
    
    # Check if command failed
    if cmd_result.status == 'failed' or (cmd_result.exit_code and cmd_result.exit_code != 0):
        return VMStatus.ERROR
    
    # Check command type and success
    command = cmd_result.command.lower() if cmd_result.command else ""
    
    # Docker/service commands
    if any(keyword in command for keyword in ['docker run', 'systemctl start', 'service start']):
        if cmd_result.status == 'success' or cmd_result.exit_code == 0:
            return VMStatus.READY
        else:
            return VMStatus.BUSY
    
    # Installation commands
    if any(keyword in command for keyword in ['apt install', 'yum install', 'pip install', 'npm install']):
        if cmd_result.status == 'success' or cmd_result.exit_code == 0:
            return VMStatus.READY
        else:
            return VMStatus.BUSY
    
    # Stop commands
    if any(keyword in command for keyword in ['stop', 'shutdown', 'halt']):
        if cmd_result.status == 'success' or cmd_result.exit_code == 0:
            return VMStatus.STOPPING
        else:
            return VMStatus.BUSY
    
    # Default: if command succeeded, VM is ready; if failed, error
    if cmd_result.status == 'success' or cmd_result.exit_code == 0:
        return VMStatus.READY
    else:
        return VMStatus.BUSY

class ProcessStatus(Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"
    UNKNOWN = "unknown"

@dataclass
class HostProcessInfo:
    process_id: str
    vm_name: str
    agent_id: str
    command: str
    status: ProcessStatus = ProcessStatus.UNKNOWN
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    log_file_host: str = ""
    exit_code: Optional[int] = None
    error_message: Optional[str] = None
    output_lines: List[str] = field(default_factory=list)
    process_thread: Optional[threading.Thread] = None
    stop_event: Optional[threading.Event] = None
    log_queue: Optional[Queue] = None

class VMStatus(Enum):
    IDLE = "idle"
    READY = "ready"
    BUSY = "busy"
    STARTING = "starting"
    STOPPING = "stopping"
    ERROR = "error"
@dataclass
class AgentRequest:
    agent_id: str
    cpu: Optional[int] = 1
    memory: Optional[str] = "1G"
    disk: Optional[str] = "5G"
    image: Optional[str] = None
    cloud_init: Optional[str] = None
    priority: int = 0
    enable_cloning: Optional[bool] = False

@dataclass
class BaseVMRequest:
    vm_name: str
    cloud_init_path: str
    cpu: int = 2
    memory: str = "2G"
    disk: str = "10G"
    image: Optional[str] = None

class HostProcessTracker:
    """Tracks processes running on the host that send commands to VMs"""

    def __init__(self, vm_name: str, multipass_cmd: str, log_dir: str = LOG_DIR, 
                 execution_mode: str = "login_shell"):
        self.vm_name = vm_name
        self.multipass_cmd = multipass_cmd
        self.log_dir = log_dir
        self.execution_mode = execution_mode  # "login_shell", "interactive", "minimal", "custom"
        self.processes: Dict[str, HostProcessInfo] = {}
        self.lock = threading.Lock()
        
        # Ensure log directory exists
        os.makedirs(self.log_dir, exist_ok=True)
    
    def execute_command(self, command: str, agent_id: str) -> HostProcessInfo:
        """Start a command execution in a separate thread and track it on the host"""
        process_id = str(uuid.uuid4())
        log_filename = f"{self.vm_name}_{process_id}.log"
        logging_dir = os.path.join(self.log_dir, agent_id)
        os.makedirs(logging_dir, exist_ok=True)
        log_file_host = os.path.join(logging_dir, log_filename)
        
        # Create process info
        process_info = HostProcessInfo(
            process_id=process_id,
            vm_name=self.vm_name,
            agent_id=agent_id,
            command=command,
            start_time=datetime.now(),
            log_file_host=log_file_host,
            status=ProcessStatus.RUNNING,
            log_queue=Queue(),
            stop_event=threading.Event()
        )
        
        # Start the execution thread
        process_info.process_thread = threading.Thread(
            target=self._execute_command_thread,
            args=(process_info,),
            daemon=True
        )
        
        with self.lock:
            self.processes[process_id] = process_info
        
        process_info.process_thread.start()
        
        # Start log writer thread
        log_writer_thread = threading.Thread(
            target=self._log_writer_thread,
            args=(process_info,),
            daemon=True
        )
        log_writer_thread.start()
        
        return process_info
    
    def _execute_command_thread(self, process_info: HostProcessInfo):
        """Thread function that executes the command via multipass exec"""
        try:
            # Log command start
            start_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting command: {process_info.command}\n"
            start_msg += f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Process ID: {process_info.process_id}\n"
            start_msg += f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] VM: {process_info.vm_name}\n"
            start_msg += f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Agent: {process_info.agent_id}\n"
            start_msg += "=" * 80 + "\n"
            
            process_info.log_queue.put(start_msg)
            process_info.output_lines.append(start_msg)
            
            # Build command based on execution mode
            cmd = self._build_execution_command(process_info)
            
            # Start the subprocess
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Merge stderr with stdout
                universal_newlines=True,
                bufsize=1  # Line buffered
            )
            
            # Read output line by line
            while True:
                if process_info.stop_event.is_set():
                    # Kill the process if stop event is set
                    process.terminate()
                    time.sleep(1)
                    if process.poll() is None:
                        process.kill()
                    process_info.status = ProcessStatus.KILLED
                    break
                
                # Check if process is still running
                if process.poll() is not None:
                    # Process has finished, read any remaining output
                    remaining_output = process.stdout.read()
                    if remaining_output:
                        for line in remaining_output.split('\n'):
                            if line.strip():
                                timestamped_line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {line}\n"
                                process_info.log_queue.put(timestamped_line)
                                process_info.output_lines.append(timestamped_line)
                    break
                
                # Read line from stdout
                try:
                    line = process.stdout.readline()
                    if line:
                        timestamped_line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {line.rstrip()}\n"
                        process_info.log_queue.put(timestamped_line)
                        process_info.output_lines.append(timestamped_line)
                    else:
                        # No more output, but process might still be running
                        time.sleep(0.1)
                except Exception as e:
                    error_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Error reading output: {str(e)}\n"
                    process_info.log_queue.put(error_msg)
                    process_info.output_lines.append(error_msg)
                    break
            
            # Get exit code
            process_info.exit_code = process.returncode
            
            # Determine final status
            if process_info.status != ProcessStatus.KILLED:
                if process_info.exit_code == 0:
                    process_info.status = ProcessStatus.COMPLETED
                else:
                    process_info.status = ProcessStatus.FAILED
            
            # Log completion
            end_msg = "=" * 80 + "\n"
            end_msg += f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Command finished\n"
            end_msg += f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Status: {process_info.status.value}\n"
            end_msg += f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Exit code: {process_info.exit_code}\n"
            
            process_info.log_queue.put(end_msg)
            process_info.output_lines.append(end_msg)
            
        except Exception as e:
            process_info.status = ProcessStatus.FAILED
            process_info.error_message = str(e)
            error_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ERROR: {str(e)}\n"
            process_info.log_queue.put(error_msg)
            process_info.output_lines.append(error_msg)
        
        finally:
            process_info.end_time = datetime.now()
            # Signal log writer to stop
            process_info.log_queue.put(None)
    
    def _build_execution_command(self, process_info: HostProcessInfo) -> List[str]:
        """Build the appropriate execution command based on mode"""
        
        if self.execution_mode == "login_shell":
            # Use bash -l to load full login environment
            wrapped_command = f"""
            source /etc/profile 2>/dev/null || true
            source ~/.profile 2>/dev/null || true  
            source ~/.bashrc 2>/dev/null || true
            cd ~
            {process_info.command}
            """
            return [
                self.multipass_cmd, "exec", process_info.vm_name, "--",
                "bash", "-l", "-c", wrapped_command
            ]
        
        elif self.execution_mode == "interactive":
            # Simulate interactive shell by explicitly loading bashrc
            wrapped_command = f"""
            export PS1='$ '
            [ -f ~/.bashrc ] && source ~/.bashrc
            cd ~
            {process_info.command}
            """
            return [
                self.multipass_cmd, "exec", process_info.vm_name, "--",
                "bash", "-i", "-c", wrapped_command
            ]
        
        elif self.execution_mode == "custom":
            # Full custom environment setup - most comprehensive
            wrapped_command = f"""
            # Load system environment
            source /etc/environment 2>/dev/null || true
            source /etc/profile 2>/dev/null || true
            
            # Load user environment
            source ~/.profile 2>/dev/null || true
            source ~/.bash_profile 2>/dev/null || true
            source ~/.bashrc 2>/dev/null || true
            
            # Set working directory to home
            cd ~
            
            # Export common variables
            export HOME=/home/ubuntu
            export USER=ubuntu
            export SHELL=/bin/bash
            
            # Add common paths
            export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:$PATH"
            
            # Execute the actual command
            {process_info.command}
            """
            return [
                self.multipass_cmd, "exec", process_info.vm_name, "--",
                "bash", "-l", "-c", wrapped_command
            ]
        
        else:  # minimal mode (original behavior)
            return [
                self.multipass_cmd, "exec", process_info.vm_name, "--",
                "bash", "-c", process_info.command
            ]
    
    def _log_writer_thread(self, process_info: HostProcessInfo):
        """Thread function that writes logs to file in real-time"""
        try:
            with open(process_info.log_file_host, 'w') as log_file:
                while True:
                    try:
                        # Get log entry from queue (blocking with timeout)
                        log_entry = process_info.log_queue.get(timeout=1)
                        
                        if log_entry is None:
                            # None is the signal to stop
                            break
                        
                        # Write to file and flush immediately for real-time logging
                        log_file.write(log_entry)
                        log_file.flush()
                        
                    except Empty:
                        # Timeout occurred, check if process is still running
                        if process_info.status != ProcessStatus.RUNNING:
                            break
                        continue
                        
        except Exception as e:
            logging.error(f"Error in log writer for process {process_info.process_id}: {e}")
    
    def kill_process(self, process_id: str) -> bool:
        """Kill a specific process"""
        with self.lock:
            if process_id not in self.processes:
                return False
            
            process_info = self.processes[process_id]
            
            if process_info.status == ProcessStatus.RUNNING:
                process_info.stop_event.set()
                return True
            
            return False
    
    def get_process_info(self, process_id: str) -> Optional[HostProcessInfo]:
        """Get information about a specific process"""
        with self.lock:
            return self.processes.get(process_id)
    
    def list_processes(self, agent_id: Optional[str] = None) -> List[HostProcessInfo]:
        """List all processes, optionally filtered by agent_id"""
        with self.lock:
            processes = list(self.processes.values())
            if agent_id:
                processes = [p for p in processes if p.agent_id == agent_id]
            return processes
    
    def get_process_logs(self, process_id: str, lines: int = 100) -> str:
        """Get recent logs for a process"""
        with self.lock:
            if process_id not in self.processes:
                return ""
            
            process_info = self.processes[process_id]
            
            try:
                if os.path.exists(process_info.log_file_host):
                    with open(process_info.log_file_host, 'r') as f:
                        content = f.read()
                        lines_list = content.split('\n')
                        return '\n'.join(lines_list[-lines:]) if len(lines_list) > lines else content
                else:
                    # Return in-memory logs if file doesn't exist yet
                    return ''.join(process_info.output_lines[-lines:])
            except Exception as e:
                logging.error(f"Error reading logs for process {process_id}: {e}")
                return ""
    
    def cleanup_completed_processes(self, max_age_hours: int = 24):
        """Clean up completed processes older than max_age_hours"""
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        
        with self.lock:
            to_remove = []
            for process_id, process_info in self.processes.items():
                if (process_info.status in [ProcessStatus.COMPLETED, ProcessStatus.FAILED, ProcessStatus.KILLED] 
                    and process_info.end_time 
                    and process_info.end_time < cutoff_time):
                    to_remove.append(process_id)
            
            for process_id in to_remove:
                del self.processes[process_id]
                logging.info(f"Cleaned up old process {process_id}")

class MultipassVM:
    def __init__(self, vm_name, multipass_cmd, execution_mode="login shell"):
        self.cmd = multipass_cmd
        self.vm_name = vm_name
        self.status = VMStatus.IDLE
        self.assigned_agent = None
        self.lock = threading.Lock()
        
        # Host-side process tracker with configurable execution mode
        self.process_tracker = HostProcessTracker(vm_name, multipass_cmd, execution_mode=execution_mode)
        
    def info(self):
        cmd = [self.cmd, "info", self.vm_name, "--format", "json"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"Multipass info command failed: {result.stderr}")
        return json.loads(result.stdout)
    
    def delete(self):
        # Kill all running processes first
        for process_info in self.process_tracker.list_processes():
            if process_info.status == ProcessStatus.RUNNING:
                self.process_tracker.kill_process(process_info.process_id)
        
        cmd = [self.cmd, "delete", self.vm_name, "--purge"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"Error deleting Multipass VM {self.vm_name}: {result.stderr}")

    def execute_and_track_process(self, command: str, agent_id: str) -> HostProcessInfo:
        """
        Execute a command in the VM and track it on the host side
        """
        self.status = VMStatus.BUSY
        return self.process_tracker.execute_command(command, agent_id)

    def kill_process(self, process_id: str) -> bool:
        """Kill a specific process by process_id"""
        return self.process_tracker.kill_process(process_id)

    def get_process_info(self, process_id: str) -> Optional[HostProcessInfo]:
        """Get information about a specific process"""
        return self.process_tracker.get_process_info(process_id)

    def list_processes(self, agent_id: Optional[str] = None) -> List[HostProcessInfo]:
        """List all processes, optionally filtered by agent_id"""
        return self.process_tracker.list_processes(agent_id)

    def get_process_logs(self, process_id: str, lines: int = 100) -> str:
        """Get recent logs for a process"""
        return self.process_tracker.get_process_logs(process_id, lines)

    def stop(self):
        # Kill all running processes
        for process_info in self.process_tracker.list_processes():
            if process_info.status == ProcessStatus.RUNNING:
                self.process_tracker.kill_process(process_info.process_id)
        
        self.status = VMStatus.STOPPING
        cmd = [self.cmd, "stop", self.vm_name]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"Error stopping Multipass VM {self.vm_name}: {result.stderr}")
    
    def start(self):
        temp = self.status
        self.status = VMStatus.STARTING
        cmd = [self.cmd, "start", self.vm_name]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            self.status = VMStatus.ERROR
            raise Exception(f"Error starting Multipass VM {self.vm_name}: {result.stderr}")
        self.status = temp

    def mount_directory(self, host_path, vm_mount_path):
        """Mount a host directory to the VM"""
        cmd = [self.cmd, "mount", host_path, f"{self.vm_name}:{vm_mount_path}"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"Error mounting {host_path} to {self.vm_name}:{vm_mount_path}: {result.stderr}")
        print(f"Successfully mounted {host_path} to {self.vm_name}:{vm_mount_path}")
    
    def unmount_directory(self, vm_mount_path):
        """Unmount a directory from the VM"""
        cmd = [self.cmd, "umount", f"{self.vm_name}:{vm_mount_path}"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"Error unmounting {self.vm_name}:{vm_mount_path}: {result.stderr}")
        print(f"Successfully unmounted {self.vm_name}:{vm_mount_path}")
    
    def list_mounts(self):
        """List all mounts for the VM"""
        cmd = [self.cmd, "info", self.vm_name, "--format", "json"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"Error getting VM info: {result.stderr}")
        
        import json
        vm_info = json.loads(result.stdout)
        mounts = vm_info.get("info", {}).get(self.vm_name, {}).get("mounts", {})
        
        print(f"Mounts for {self.vm_name}:")
        for vm_path, host_path in mounts.items():
            print(f"  {host_path} -> {vm_path}")
        
        return mounts

class AsyncMultipassController:
    def __init__(self, multipass_cmd="multipass", max_vms=10):
        self.max_vms = max_vms
        self.cmd = multipass_cmd
        self.executor = ThreadPoolExecutor(max_workers=max_vms)
        self.base_image_timeout =1800
        # VM management
        self.active_vms: Dict[str, MultipassVM] = {}
        self.vm_pool: List[MultipassVM] = []
        self.request_queue: List[AgentRequest] = []
        
        # Control flags
        self.running = True
        self.scheduler_task = None
        
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
        self.base_vms = {}

    def update_vm_status_on_log(self, agent_id: str, vm_name: str, LOG_DIR: str = LOG_DIR):
        """Update VM status based on log file with advanced command parsing"""
        log_dir = os.path.join(LOG_DIR,f'{agent_id}', f'{vm_name}')
        
        if not os.path.exists(log_dir):
            self.logger.warning(f"Log directory not found: {log_dir}")
            return
        
        latest_command_result = None
        latest_timestamp = None
        
        # Process all log files
        for log_file_name in os.listdir(log_dir):
            if not log_file_name.endswith('.log'):
                continue
            
            log_file_path = os.path.join(log_dir, log_file_name)
            
            try:
                with open(log_file_path, 'r', encoding='utf-8') as f:
                    lines = [line.rstrip('\n') for line in f.readlines()]
            except Exception as e:
                self.logger.error(f"Error reading log file {log_file_path}: {e}")
                continue
            
            if not lines:
                continue
            
            # Find all command blocks in this file
            i = 0
            while i < len(lines):
                if 'Starting command:' in lines[i]:
                    cmd_result = parse_command_block(lines, i)
                    if cmd_result:
                        # Convert timestamp to datetime for comparison
                        try:
                            cmd_timestamp = datetime.strptime(cmd_result.timestamp, '%Y-%m-%d %H:%M:%S')
                            if latest_timestamp is None or cmd_timestamp > latest_timestamp:
                                latest_timestamp = cmd_timestamp
                                latest_command_result = cmd_result
                        except ValueError:
                            # If timestamp parsing fails, still use the command result
                            latest_command_result = cmd_result
                        
                        # Skip to next potential command block
                        while i < len(lines) and not ('Starting command:' in lines[i] and i > 0):
                            i += 1
                    else:
                        i += 1
                else:
                    i += 1
        
        # Update VM status based on latest command result
        if vm_name not in self.active_vms:
            self.logger.warning(f"VM {vm_name} not found in active_vms")
            return
        
        if latest_command_result:
            new_status = determine_vm_status_from_command(latest_command_result)
            old_status = self.active_vms[vm_name].status
            
            self.active_vms[vm_name].status = new_status
            
            # Log status change with details
            self.logger.info(f"VM {vm_name} status updated: {old_status} -> {new_status}")
            if latest_command_result.error_message and new_status == VMStatus.ERROR:
                self.logger.error(f"VM {vm_name} error: {latest_command_result.error_message}")
            
            # Store last command info for debugging
            if hasattr(self.active_vms[vm_name], 'last_command'):
                self.active_vms[vm_name].last_command = latest_command_result.command
                self.active_vms[vm_name].last_command_status = latest_command_result.status
                self.active_vms[vm_name].last_command_time = latest_command_result.timestamp
        else:
            # No command blocks found, fallback to simple log analysis
            self.logger.info(f"No command blocks found for {vm_name}, using fallback analysis")
            return

    def _fallback_status_update(self, vm_name: str, log_dir: str):
        """Fallback method for status update when no command blocks are found"""
        latest_log_line = None
        latest_timestamp = None
        
        for log_file_name in os.listdir(log_dir):
            if not log_file_name.endswith('.log'):
                continue
                
            log_file_path = os.path.join(log_dir, log_file_name)
            try:
                with open(log_file_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                if lines:
                    last_line = lines[-1].strip()
                    # Try to extract timestamp if available
                    timestamp_match = re.match(r'\[([^\]]+)\]', last_line)
                    if timestamp_match:
                        try:
                            line_timestamp = datetime.strptime(timestamp_match.group(1), '%Y-%m-%d %H:%M:%S')
                            if latest_timestamp is None or line_timestamp > latest_timestamp:
                                latest_timestamp = line_timestamp
                                latest_log_line = last_line
                        except ValueError:
                            latest_log_line = last_line
            except Exception as e:
                self.logger.error(f"Error reading log file {log_file_path}: {e}")
        
        # Update status based on latest log line
        if latest_log_line:
            line_lower = latest_log_line.lower()
            if any(keyword in line_lower for keyword in ['error', 'failed', 'exception', 'traceback']):
                self.active_vms[vm_name].status = VMStatus.READY
            elif any(keyword in line_lower for keyword in ['successfully', 'completed', 'ready', 'started']):
                self.active_vms[vm_name].status = VMStatus.READY
            elif any(keyword in line_lower for keyword in ['starting', 'installing', 'downloading']):
                self.active_vms[vm_name].status = VMStatus.BUSY
            else:
                self.active_vms[vm_name].status = VMStatus.BUSY
    def _check_image_exists(self, cloud_init_path: str) -> bool:
        """Check if a specific image exists"""
        cloud_init = self.encode_cloud_init(cloud_init_path)
        for vm_name, vm_info in self.base_vms.items():
            if vm_info.get("cloud_init") == cloud_init:
                return vm_name
        return None

    def encode_cloud_init(self, cloud_init_path: str) -> str:
        if cloud_init_path:
            with open(cloud_init_path, 'r') as f:
                cloud_init_content = f.read()
            cloud_init = sha256(cloud_init_content.encode('utf-8')).hexdigest()
            return cloud_init
        return None
    
    def create_base_vm(self, vm_name, cloud_init_path, cpu=2, memory="2G", disk="10G", image=None):
        """Create a base VM that can be cloned for other agents"""
        try:
            cloud_init = self.encode_cloud_init(cloud_init_path)
            self.base_vms[vm_name] = {
                "cpu": cpu,
                "memory": memory,
                "disk": disk,
                "image": image,
                "cloud_init": cloud_init,
                "cloud_init_path": cloud_init_path
            }
            
            cmd = [self.cmd, "launch", "-c", str(cpu), "-m", memory, "-d", disk, "-n", vm_name]
            if image:
                cmd.append(image)
            if cloud_init:
                cmd.extend(["--cloud-init", cloud_init_path])
            cmd.extend(['--timeout', str(self.base_image_timeout)])
            subprocess.run(cmd, check=True)
            
        except subprocess.CalledProcessError as e:
            print(f"Error creating base VM {vm_name}: {e}")
            existing_vm = str(e).find("already exists") != -1
            if existing_vm:
                existing_vm = str(e).find(f'{vm_name}') != -1
                print(f"VM {vm_name} already exists, cloning from {existing_vm}")
                return {"success": True, "vm_name": existing_vm, "cloud_init": cloud_init}
            return {"success": False, "error": str(e)}
        finally:
            subprocess.run([self.cmd, "stop", vm_name], check=True)
            self.logger.info(f"Base VM {vm_name} created with cloud-init {cloud_init_path}")
            return {"success": True, "vm_name": vm_name, "cloud_init": cloud_init}
    
    async def create_base_vm_async(self, request: BaseVMRequest):
        """Create a base VM that can be cloned for other agents (async)"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self.executor, 
            self.create_base_vm, request.vm_name, request.cloud_init_path, 
            request.cpu, request.memory, request.disk, request.image
        )
        self.logger.info(f"Base VM {request.vm_name} created successfully")
        return True
    
    async def start_scheduler(self):
        """Start the async VM scheduler"""
        self.scheduler_task = asyncio.create_task(self._scheduler_loop())
        self.logger.info("VM scheduler started")
    
    async def stop_scheduler(self):
        """Stop the async VM scheduler"""
        self.running = False
        if self.scheduler_task:
            await self.scheduler_task
        await self.clean_up_all_vms()
        self.executor.shutdown(wait=True)
        self.logger.info("VM scheduler stopped")
    
    async def _scheduler_loop(self):
        """Main scheduler loop that processes VM requests"""
        index = 0
        while self.running:
            try:
                if self.request_queue:
                    self.request_queue.sort(key=lambda x: x.priority, reverse=True)
                    request = self.request_queue.pop(0)
                    
                    vm = await self._assign_vm_to_agent(request)
                    if vm:
                        self.logger.info(f"Assigned VM {vm.vm_name} to agent {request.agent_id}")
                        await asyncio.sleep(MCP_STARTUP_TIME)
                        self.start_mcp_server_on_vm(request.agent_id, vm.vm_name)
                        await asyncio.sleep(MCP_POSTSTARTUP_TIME)  # Allow time for MCP server to start
                index += 1
                if index % 500 == 0:
                    for vm in list(self.active_vms.values()):
                        self.update_vm_status_on_log(vm.assigned_agent, vm.vm_name)
                if index == 10000:
                    index = 0
                await asyncio.sleep(1)
                
            except Exception as e:
                self.logger.error(f"Scheduler error: {e}")
                await asyncio.sleep(5)
    
    async def _assign_vm_to_agent(self, request: AgentRequest) -> Optional[MultipassVM]:
        """Assign a VM to an agent based on their requirements"""
        available_vm = None
        for vm in self.vm_pool:
            with vm.lock:
                if vm.status == VMStatus.IDLE and vm.assigned_agent is None:
                    available_vm = vm
                    break
        
        if not available_vm and len(self.active_vms) < self.max_vms:
            try:
                available_vm = await self._create_vm_for_request(request)
                
            except Exception as e:
                self.logger.error(f"Failed to create VM for agent {request.agent_id}: {e}")
                return None
        
        if available_vm:
            with available_vm.lock:
                available_vm.assigned_agent = request.agent_id
                available_vm.status = VMStatus.READY
            return available_vm
        
        self.request_queue.insert(0, request)
        return None
    
    async def _create_vm_for_request(self, request: AgentRequest) -> MultipassVM:
        """Create a new VM for a specific request"""
        vm_name = Haikunator().haikunate(token_length=0)
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self.executor, 
            self._launch_vm_sync, 
            vm_name, request.cpu, request.disk, request.memory, 
            request.image, request.cloud_init, request.enable_cloning
        )
        vm = MultipassVM(vm_name, self.cmd, execution_mode="custom")
        
        self.active_vms[vm_name] = vm
        self.vm_pool.append(vm)
        return vm
    
    def _launch_vm_sync(self, vm_name: str, cpu: int, disk: str, memory: str, 
                       image: Optional[str], cloud_init: Optional[str], enable_cloning: bool = False):
        """Synchronous VM launch for thread pool execution"""
        existing_vm_name = None
        if cloud_init:
            existing_vm_name = self._check_image_exists(cloud_init)
        
        if existing_vm_name and enable_cloning:
            self.logger.info(f"Cloning existing VM {existing_vm_name} to {vm_name}")
            cmd = [self.cmd, "clone", existing_vm_name, "--name", vm_name]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(f"Error cloning Multipass VM {existing_vm_name}: {result.stderr}")
            cmd = [self.cmd, "start", vm_name]
            result = subprocess.run(cmd, capture_output=True, text=True)
        else:
            self.logger.info(f"Creating new VM {vm_name}")
            cmd = [self.cmd, "launch","-c", str(cpu), "-d", disk, "-n", vm_name, "-m", memory]
            if cloud_init:
                cmd.extend(["--cloud-init", cloud_init])
            if image and image != "ubuntu-lts":
                cmd.append(image)
            
            result = subprocess.run(cmd, capture_output=True, text=True)
        # create a bridge network for vm
        # multipass launch --network name=br0 --name <vm_name>
        if result.returncode != 0:
            raise Exception(f"Error launching Multipass VM {vm_name}: {result.stderr}")
        self.configure_vm_network(vm_name)

    def configure_vm_network(self, vm_name):
        """Configure network inside the VM"""
        try:
            # Example: Enable SSH or configure specific network settings
            cmd = [self.cmd, "exec", vm_name, "--", "sudo", "systemctl", "enable", "ssh"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                self.logger.warning(f"Failed to configure network for {vm_name}: {result.stderr}")
        except Exception as e:
            self.logger.warning(f"Network configuration failed for {vm_name}: {e}")
    def start_mcp_server_on_vm(self, assigned_agent: str, vm_name: str):
        """Start the MCP server on the VM"""
        try:
            res = execute_command(agent_id=assigned_agent, vm_name=vm_name, command="/home/ubuntu/start_server.sh")
            self.logger.info(f"Started MCP server on {vm_name}: {res}") 
            self.active_vms[vm_name].status = VMStatus.READY
            return res
        except Exception as e:
            self.logger.warning(f"Error starting MCP server on {vm_name}: {e}")
    async def request_vm_async(self, request: AgentRequest) -> None:
        """Request a VM for an agent (async)"""
        self.request_queue.append(request)
        self.logger.info(f"VM request queued for agent {request.agent_id}")

    
    async def release_vm_async(self, agent_id: str, vm_name: str) -> bool:
        """Release a VM from an agent (async)"""
        if vm_name not in self.active_vms:
            return False
        
        vm = self.active_vms[vm_name]
        
        with vm.lock:
            if vm.assigned_agent != agent_id:
                return False
            
            vm.assigned_agent = None
            vm.status = VMStatus.IDLE
        
        self.logger.info(f"VM {vm_name} released by agent {agent_id}")
        return True
    
    async def cleanup_vm_async(self, vm_name: str) -> bool:
        """Completely remove a VM (async)"""
        if vm_name not in self.active_vms:
            return False
        
        vm = self.active_vms[vm_name]
        
        if vm in self.vm_pool:
            self.vm_pool.remove(vm)
        
        del self.active_vms[vm_name]
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self.executor, vm.delete)
        
        self.logger.info(f"VM {vm_name} cleaned up")
        return True
    
    def get_vm_status(self) -> Dict[str, Dict[str, Any]]:
        """Get current VM status"""
        return {
            vm_name: {
                "status": vm.status.value,
                "assigned_agent": vm.assigned_agent,
                "process_count": len(vm.process_tracker.processes)
            }
            for vm_name, vm in self.active_vms.items()
        }
    
    def get_detailed_vm_info(self, vm_name: str) -> Dict[str, Any]:
        """Get detailed information about a VM"""
        detailed_info = {}
        vm = self.active_vms.get(vm_name)
        try:
            info = vm.info()
            detailed_info[vm_name] = {
                "status": vm.status.value,
                "assigned_agent": vm.assigned_agent,
                "process_count": len(vm.process_tracker.processes),
                "info": info
            }
        except Exception as e:
            detailed_info[vm_name] = {
                "status": "error",
                "error": str(e)
            }
        return detailed_info
    
    async def clean_up_all_vms(self):
        """Clean up all VMs"""
        if len(self.active_vms) == 0:
            self.logger.info("No active VMs to clean up")
            return True
        
        for vm_name in list(self.active_vms.keys()):
            try:
                await self.cleanup_vm_async(vm_name)
            except Exception as e:
                self.logger.error(f"Error cleaning up VM {vm_name}: {e}")
        
        self.vm_pool.clear()
        self.active_vms.clear()
        self.logger.info("All VMs cleaned up")
        return True

    def transfer_logs_to_host_alt(self, agent_id: str, vm_name: str, log_dir: str = LOG_DIR, vm_logs_dir: str = "/home/ubuntu/vm_logs"):
        """Transfer logs from VM to host (alternative - log files only)"""
        if vm_name not in self.active_vms:
            raise ValueError(f"VM {vm_name} not found")
        if agent_id not in self.active_vms[vm_name].assigned_agent:
            raise ValueError(f"VM {vm_name} is not assigned to agent {agent_id}")

        log_dir = os.path.join(log_dir, agent_id, vm_name)
        os.makedirs(log_dir, exist_ok=True)
        
        # First, try to transfer the entire directory
        cmd = [self.cmd, "transfer", "-r", f"{vm_name}:{vm_logs_dir}/", log_dir]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            # If that fails, try to transfer individual log files
            # First check what files exist
            check_cmd = [self.cmd, "exec", vm_name, "--", "find", vm_logs_dir, "-name", "*.log", "-type", "f"]
            check_result = subprocess.run(check_cmd, capture_output=True, text=True)
            
            if check_result.returncode == 0 and check_result.stdout.strip():
                log_files = check_result.stdout.strip().split('\n')
                for log_file in log_files:
                    if log_file.strip():
                        transfer_cmd = [self.cmd, "transfer", f"{vm_name}:{log_file}", log_dir]
                        subprocess.run(transfer_cmd, capture_output=True, text=True)
            else:
                raise Exception(f"Error pulling VM logs: {result.stderr}")
        
        print(f"Logs for VM {vm_name} transferred to {log_dir}")
# FastAPI endpoints
from fastapi import FastAPI, HTTPException
import uvicorn
from datetime import timedelta

api = FastAPI()
max_vms = 10
controller = AsyncMultipassController(max_vms=max_vms)

@api.post("/start_scheduler")
async def start_scheduler():
    await controller.start_scheduler()
    return {"status": "success", "message": "Scheduler started"}

@api.post("/stop_scheduler")
async def stop_scheduler():
    await controller.stop_scheduler()
    return {"status": "success", "message": "Scheduler stopped"}

@api.post("/create_base_vm")
async def create_base_vm_async(request: BaseVMRequest):
    return await controller.create_base_vm_async(request)

@api.post("/request_vm_async")
async def request_vm_async(request: AgentRequest):
    await controller.request_vm_async(request)
    return {"status": "success", "message": f"VM requested for agent {request.agent_id}"}

@api.post("/request_vm")
async def request_vm(request: AgentRequest):
    vm = await controller._assign_vm_to_agent(request)
    if vm:
        controller.logger.info(f"Assigned VM {vm.vm_name} to agent {request.agent_id}")
        await asyncio.sleep(MCP_STARTUP_TIME)
        controller.start_mcp_server_on_vm(request.agent_id, vm.vm_name)
        await asyncio.sleep(MCP_POSTSTARTUP_TIME)  # Allow time for MCP server to start
    return {"status": "success", "message": f"VM requested for agent {request.agent_id}"}

@api.post("/release_vm/{agent_id}/{vm_name}")
async def release_vm_async(agent_id: str, vm_name: str):
    success = await controller.release_vm_async(agent_id, vm_name)
    if not success:
        raise HTTPException(status_code=404, detail=f"VM {vm_name} not found or not assigned to agent {agent_id}")
    return {"status": "success", "message": f"VM {vm_name} released by agent {agent_id}"}

@api.post("/cleanup_vm")
async def cleanup_vm_async(vm_name: str):
    success = await controller.cleanup_vm_async(vm_name)
    if not success:
        raise HTTPException(status_code=404, detail=f"VM {vm_name} not found")
    return {"status": "success", "message": f"VM {vm_name} cleaned up"}

# Process management endpoints - all host-side tracking
@api.post("/execute_command/{agent_id}/{vm_name}")
def execute_command(agent_id: str, vm_name: str, command: str):
    """Execute a command in a specific VM and track it on the host"""
    log_dir = os.path.join(LOG_DIR, agent_id, vm_name)
    os.makedirs(log_dir, exist_ok=True)
    if vm_name not in controller.active_vms:
        raise HTTPException(status_code=404, detail=f"VM {vm_name} not found")
    
    vm = controller.active_vms[vm_name]
    if vm.assigned_agent != agent_id:
        raise HTTPException(status_code=403, detail=f"VM {vm_name} is not assigned to agent {agent_id}")
    
    try:
        # Execute command and track on host side
        process_info = vm.execute_and_track_process(command, agent_id)
        return {
            "status": "success",
            "process_id": process_info.process_id,
            "log_file": process_info.log_file_host,
            "start_time": process_info.start_time.isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api.get("/process_info/{agent_id}/{vm_name}/{process_id}")
async def get_process_info(agent_id: str, vm_name: str, process_id: str):
    """Get information about a specific process"""
    if vm_name not in controller.active_vms:
        raise HTTPException(status_code=404, detail=f"VM {vm_name} not found")
    
    vm = controller.active_vms[vm_name]
    if vm.assigned_agent != agent_id:
        raise HTTPException(status_code=403, detail=f"VM {vm_name} is not assigned to agent {agent_id}")
    
    process_info = vm.get_process_info(process_id)
    if not process_info:
        raise HTTPException(status_code=404, detail=f"Process {process_id} not found")
    
    return {
        "status": "success",
        "process_info": {
            "process_id": process_info.process_id,
            "vm_name": process_info.vm_name,
            "agent_id": process_info.agent_id,
            "command": process_info.command,
            "status": process_info.status.value,
            "start_time": process_info.start_time.isoformat() if process_info.start_time else None,
            "end_time": process_info.end_time.isoformat() if process_info.end_time else None,
            "exit_code": process_info.exit_code,
            "log_file_host": process_info.log_file_host,
            "error_message": process_info.error_message,
            "output_line_count": len(process_info.output_lines)
        }
    }

@api.get("/list_processes/{agent_id}")
async def list_processes(agent_id: str, vm_name: str = None):
    """List all processes for an agent, optionally filtered by VM"""
    processes = []
    
    vms_to_check = [controller.active_vms[vm_name]] if vm_name and vm_name in controller.active_vms else controller.active_vms.values()
    
    for vm in vms_to_check:
        if vm.assigned_agent == agent_id:
            vm_processes = vm.list_processes(agent_id)
            for process_info in vm_processes:
                processes.append({
                    "process_id": process_info.process_id,
                    "vm_name": process_info.vm_name,
                    "command": process_info.command,
                    "status": process_info.status.value,
                    "start_time": process_info.start_time.isoformat() if process_info.start_time else None,
                    "end_time": process_info.end_time.isoformat() if process_info.end_time else None,
                    "exit_code": process_info.exit_code,
                    "output_line_count": len(process_info.output_lines)
                })
    
    return {
        "status": "success",
        "processes": processes
    }

@api.delete("/kill_process/{agent_id}/{vm_name}/{process_id}")
async def kill_process(agent_id: str, vm_name: str, process_id: str):
    """Kill a specific process"""
    if vm_name not in controller.active_vms:
        raise HTTPException(status_code=404, detail=f"VM {vm_name} not found")
    
    vm = controller.active_vms[vm_name]
    if vm.assigned_agent != agent_id:
        raise HTTPException(status_code=403, detail=f"VM {vm_name} is not assigned to agent {agent_id}")
    
    success = vm.kill_process(process_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Process {process_id} not found or already terminated")
    
    return {"status": "success", "message": f"Process {process_id} killed"}

@api.get("/process_logs/{agent_id}/{vm_name}/{process_id}")
async def get_process_logs(agent_id: str, vm_name: str, process_id: str, lines: int = 100):
    """Get recent logs for a process"""
    if vm_name not in controller.active_vms:
        raise HTTPException(status_code=404, detail=f"VM {vm_name} not found")
    
    vm = controller.active_vms[vm_name]
    if vm.assigned_agent != agent_id:
        raise HTTPException(status_code=403, detail=f"VM {vm_name} is not assigned to agent {agent_id}")
    
    process_info = vm.get_process_info(process_id)
    if not process_info:
        raise HTTPException(status_code=404, detail=f"Process {process_id} not found")
    
    logs = vm.get_process_logs(process_id, lines)
    
    return {
        "status": "success",
        "process_id": process_id,
        "logs": logs,
        "lines_requested": lines,
        "process_status": process_info.status.value
    }

@api.get("/vm_status")
async def get_vm_status():
    status = controller.get_vm_status()
    return {"status": "success", "data": status}

@api.get("/vm_info/{agent_id}")
async def get_detailed_vm_info_from_agent_id(agent_id: str):
    """Get detailed information about a specific agent's VMs"""
    status = controller.get_vm_status()
    detailed_infos = {}
    
    for vm_name, vm_info in status.items():
        if vm_info.get("assigned_agent") == agent_id:
            detailed_info = controller.get_detailed_vm_info(vm_name)
            detailed_infos[vm_name] = detailed_info
    
    if not detailed_infos:
        raise HTTPException(status_code=404, detail=f"No VMs found for agent {agent_id}")
    
    return {"status": "success", "data": detailed_infos}

@api.get("/get_free_assigned_vm/{agent_id}")
def get_free_assigned_vm_info(agent_id: str):
    """Get a free VM assigned to a specific agent"""
    status = controller.get_vm_status()
    filter_assigned = {k: v for k, v in status.items() if v.get("assigned_agent") == agent_id}
    filter_status = {k: v for k, v in filter_assigned.items() if v.get("status") in [VMStatus.IDLE.value, VMStatus.READY.value]}
    result = []
    
    for vm_name, vm_info in filter_status.items():
        detailed_info = controller.get_detailed_vm_info(vm_name)
        result.append({
            "vm_name": vm_name,
            "status": vm_info.get("status"),
            "assigned_agent": vm_info.get("assigned_agent"),
            "process_count": vm_info.get("process_count", 0),
            "info": detailed_info.get(vm_name, {})
        })
    
    if result:
        return {
            "status": "success",
            "data": result
        }
    return {
        "status": "NO_FREE_VM",
        "message": f"No free VM found for agent {agent_id}"
    }

# Real-time log streaming endpoint
@api.get("/stream_logs/{agent_id}/{vm_name}/{process_id}")
async def stream_process_logs(agent_id: str, vm_name: str, process_id: str, from_line: int = 0):
    """Stream logs for a process from a specific line (for real-time monitoring)"""
    if vm_name not in controller.active_vms:
        raise HTTPException(status_code=404, detail=f"VM {vm_name} not found")
    
    vm = controller.active_vms[vm_name]
    if vm.assigned_agent != agent_id:
        raise HTTPException(status_code=403, detail=f"VM {vm_name} is not assigned to agent {agent_id}")
    
    process_info = vm.get_process_info(process_id)
    if not process_info:
        raise HTTPException(status_code=404, detail=f"Process {process_id} not found")
    
    try:
        # Get logs from the specified line onwards
        if from_line < len(process_info.output_lines):
            new_lines = process_info.output_lines[from_line:]
            logs = ''.join(new_lines)
        else:
            logs = ""
        
        return {
            "status": "success",
            "process_id": process_id,
            "logs": logs,
            "from_line": from_line,
            "total_lines": len(process_info.output_lines),
            "process_status": process_info.status.value,
            "has_new_content": from_line < len(process_info.output_lines)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading log lines: {str(e)}")

# Batch operations
@api.post("/execute_multiple_commands/{agent_id}/{vm_name}")
async def execute_multiple_commands(agent_id: str, vm_name: str, commands: List[str]):
    """Execute multiple commands simultaneously in a VM"""
    if vm_name not in controller.active_vms:
        raise HTTPException(status_code=404, detail=f"VM {vm_name} not found")
    
    vm = controller.active_vms[vm_name]
    if vm.assigned_agent != agent_id:
        raise HTTPException(status_code=403, detail=f"VM {vm_name} is not assigned to agent {agent_id}")
    
    results = []
    
    # Start all commands (each will run in its own thread)
    for command in commands:
        try:
            process_info = vm.execute_and_track_process(command, agent_id)
            results.append({
                "command": command,
                "process_id": process_info.process_id,
                "status": process_info.status.value,
                "log_file": process_info.log_file_host,
                "start_time": process_info.start_time.isoformat()
            })
        except Exception as e:
            results.append({
                "command": command,
                "error": str(e),
                "status": "failed"
            })
    
    return {
        "status": "success",
        "results": results
    }

@api.delete("/kill_all_processes/{agent_id}/{vm_name}")
async def kill_all_processes(agent_id: str, vm_name: str):
    """Kill all processes for a specific agent in a VM"""
    if vm_name not in controller.active_vms:
        raise HTTPException(status_code=404, detail=f"VM {vm_name} not found")
    
    vm = controller.active_vms[vm_name]
    if vm.assigned_agent != agent_id:
        raise HTTPException(status_code=403, detail=f"VM {vm_name} is not assigned to agent {agent_id}")
    
    killed_processes = []
    processes = vm.list_processes(agent_id)
    
    for process_info in processes:
        if process_info.status == ProcessStatus.RUNNING:
            if vm.kill_process(process_info.process_id):
                killed_processes.append(process_info.process_id)
    
    return {
        "status": "success",
        "killed_processes": killed_processes,
        "count": len(killed_processes)
    }

# Maintenance endpoints
@api.post("/cleanup_old_processes/{agent_id}")
async def cleanup_old_processes(agent_id: str, max_age_hours: int = 24):
    """Clean up old completed processes for an agent"""
    cleanup_count = 0
    
    for vm_name, vm in controller.active_vms.items():
        if vm.assigned_agent == agent_id:
            old_count = len(vm.process_tracker.processes)
            vm.process_tracker.cleanup_completed_processes(max_age_hours)
            new_count = len(vm.process_tracker.processes)
            cleanup_count += (old_count - new_count)
    
    return {
        "status": "success",
        "cleaned_processes": cleanup_count,
        "message": f"Cleaned up {cleanup_count} old processes for agent {agent_id}"
    }

@api.get("/system_stats")
async def get_system_stats():
    """Get overall system statistics"""
    total_vms = len(controller.active_vms)
    active_agents = set()
    total_processes = 0
    running_processes = 0
    
    for vm in controller.active_vms.values():
        if vm.assigned_agent:
            active_agents.add(vm.assigned_agent)
        
        processes = vm.list_processes()
        total_processes += len(processes)
        running_processes += len([p for p in processes if p.status == ProcessStatus.RUNNING])
    
    return {
        "status": "success",
        "stats": {
            "total_vms": total_vms,
            "max_vms": controller.max_vms,
            "active_agents": len(active_agents),
            "total_processes": total_processes,
            "running_processes": running_processes,
            "queue_length": len(controller.request_queue)
        }
    }

# Configuration endpoints
@api.post("/set_execution_mode/{vm_name}")
async def set_execution_mode(vm_name: str, mode: str):
    """Set the execution mode for a VM (login_shell, interactive, custom, minimal)"""
    valid_modes = ["login_shell", "interactive", "custom", "minimal"]
    
    if mode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"Invalid mode. Valid modes: {valid_modes}")
    
    if vm_name not in controller.active_vms:
        raise HTTPException(status_code=404, detail=f"VM {vm_name} not found")
    
    vm = controller.active_vms[vm_name]
    vm.process_tracker.execution_mode = mode
    
    return {
        "status": "success",
        "message": f"Execution mode for VM {vm_name} set to {mode}",
        "mode": mode
    }

@api.get("/get_execution_mode/{vm_name}")
async def get_execution_mode(vm_name: str):
    """Get the current execution mode for a VM"""
    if vm_name not in controller.active_vms:
        raise HTTPException(status_code=404, detail=f"VM {vm_name} not found")
    
    vm = controller.active_vms[vm_name]
    
    return {
        "status": "success",
        "vm_name": vm_name,
        "execution_mode": vm.process_tracker.execution_mode
    }

# Health check endpoint
@api.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "scheduler_running": controller.running,
        "active_vms": len(controller.active_vms)
    }

@api.post("/start_mcp_server/{assigned_agent}/{vm_name}")
async def start_mcp_server(assigned_agent: str, vm_name: str):
    """Start the MCP server on a specific VM"""
    try:    
        vm = controller.active_vms[vm_name]
    except KeyError:
        raise HTTPException(status_code=404, detail=f"VM {vm_name} not found")
    print(f"Starting MCP server on VM {vm_name} for agent {assigned_agent}")
    print(f"VM assigned agent: {vm.assigned_agent}")
    try:
        controller.start_mcp_server_on_vm(assigned_agent,vm_name)
        return {"status": "success", "message": f"MCP server started on VM {vm_name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@api.post("/default_startup")
async def default_startup():
    """Set default startup options for new VMs"""
    await start_scheduler()
    await create_base_vm_async(BaseVMRequest(
        vm_name="default-base-vm",
        cloud_init_path="/home/danhvuive/image-init.yaml",
        cpu=4,
        memory="8G",
        disk="25G"
    ))
    # await request_vm_async(AgentRequest(
    #     agent_id="default-agent",
    #     cpu=2,
    #     memory="2G",
    #     disk="10G",
    #     image="ubuntu-lts",
    #     cloud_init="/home/danhvuive/image-init.yaml",
    #     enable_cloning=True,    ))
    return {"status": "success", "message": "Default startup completed successfully"}
@api.get("/pull_logs/{agent_id}/{vm_name}")
async def pull_logs(agent_id: str, vm_name: str):
    """Pull logs from a VM"""
    try:
        controller.transfer_logs_to_host_alt(agent_id, vm_name)
        return {"status": "success", "message": f"Logs for VM {vm_name} pulled successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(api, host="0.0.0.0", port=8010)