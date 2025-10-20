import subprocess
import asyncio
import json
import logging
import threading
import time
import os
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from queue import Queue, Empty


class ProcessStatus(Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"
    UNKNOWN = "unknown"

@dataclass
class HostProcessInfo:
    process_id: str
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
    log_writer_thread: Optional[threading.Thread] = None

class HostProcessTracker:
    """Tracks processes running on the host that send commands to VMs"""

    def __init__(self, mcp_name: str, log_dir: str = "/home/ubuntu/vm_logs", 
                execution_mode: str = "login_shell"):
        self.mcp_name = mcp_name
        self.log_dir = log_dir
        self.execution_mode = execution_mode  # "login_shell", "interactive", "minimal", "custom"
        self.processes: Dict[str, HostProcessInfo] = {}
        self.lock = threading.Lock()
        
        # Ensure log directory exists
        os.makedirs(self.log_dir, exist_ok=True)

    def execute_command(self, command: str, async_execution: bool = True) -> HostProcessInfo:
        """Start a command execution in a separate thread and track it on the host"""
        process_id = str(uuid.uuid4())
        log_filename = f"{self.mcp_name}_{process_id}.log"
        log_file_host = os.path.join(self.log_dir, log_filename)
        
        # Create process info
        process_info = HostProcessInfo(
            process_id=process_id,
            command=command,
            start_time=datetime.now(),
            log_file_host=log_file_host,
            status=ProcessStatus.RUNNING,
            log_queue=Queue(),
            stop_event=threading.Event()
        )
        
        # Start log writer thread FIRST
        process_info.log_writer_thread = threading.Thread(
            target=self._log_writer_thread,
            args=(process_info,),
            daemon=True
        )
        process_info.log_writer_thread.start()
        
        # Add to processes dict before starting execution
        with self.lock:
            self.processes[process_id] = process_info
        
        if async_execution == False:
            # SYNCHRONOUS: Execute command and wait for completion
            self._execute_command_sync(process_info)
        else:
            # ASYNCHRONOUS: Start execution thread and return immediately
            process_info.process_thread = threading.Thread(
                target=self._execute_command_thread,
                args=(process_info,),
                daemon=True
            )
            process_info.process_thread.start()
        
        return process_info
    
    def _execute_command_sync(self, process_info: HostProcessInfo):
        """Execute command synchronously (blocking)"""
        self._execute_command_thread(process_info)
    
    def _execute_command_thread(self, process_info: HostProcessInfo):
        """Thread function that executes the command via multipass exec"""
        try:
            # Log command start
            start_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting command: {process_info.command}\n"
            start_msg += f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Process ID: {process_info.process_id}\n"
            start_msg += "=" * 80 + "\n"
            
            # Add to queue and in-memory storage
            process_info.log_queue.put(start_msg)
            process_info.output_lines.append(start_msg.strip())
            
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
            
            # Read output line by line in real-time
            try:
                for line in iter(process.stdout.readline, ''):
                    if process_info.stop_event.is_set():
                        # Kill the process if stop event is set
                        process.terminate()
                        time.sleep(1)
                        if process.poll() is None:
                            process.kill()
                        process_info.status = ProcessStatus.KILLED
                        break
                    
                    if line:  # Non-empty line
                        line = line.rstrip('\n\r')  # Remove trailing newlines
                        timestamped_line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {line}\n"
                        
                        # Add to both queue and in-memory storage
                        process_info.log_queue.put(timestamped_line)
                        process_info.output_lines.append(line)
                
                # Wait for process to complete
                process.wait()
                
            except Exception as e:
                error_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Error reading output: {str(e)}\n"
                process_info.log_queue.put(error_msg)
                process_info.output_lines.append(f"Error reading output: {str(e)}")
            
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
            process_info.output_lines.append(f"Command finished - Status: {process_info.status.value}, Exit code: {process_info.exit_code}")
            
        except Exception as e:
            process_info.status = ProcessStatus.FAILED
            process_info.error_message = str(e)
            error_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ERROR: {str(e)}\n"
            process_info.log_queue.put(error_msg)
            process_info.output_lines.append(f"ERROR: {str(e)}")
        
        finally:
            process_info.end_time = datetime.now()
            # Signal log writer to stop by putting None
            process_info.log_queue.put(None)
    
    def _build_execution_command(self, process_info: HostProcessInfo) -> List[str]:
        """Build the appropriate execution command based on mode"""
        # Always use bash -c for proper command execution
        return ["bash", "-c", process_info.command]
    
    def _log_writer_thread(self, process_info: HostProcessInfo):
        """Thread function that writes logs to file in real-time"""
        try:
            # Ensure the log file exists and is writable
            with open(process_info.log_file_host, 'w', buffering=1) as log_file:  # Line buffered
                while True:
                    try:
                        # Get log entry from queue (blocking with timeout)
                        log_entry = process_info.log_queue.get(timeout=2)
                        
                        if log_entry is None:
                            # None is the signal to stop
                            log_file.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Log writer stopping\n")
                            log_file.flush()
                            break
                        
                        # Write to file and flush immediately for real-time logging
                        log_file.write(log_entry)
                        log_file.flush()  # Force write to disk
                        os.fsync(log_file.fileno())  # Force OS to write to disk
                        
                    except Empty:
                        # Timeout occurred, check if process is still running
                        if process_info.status not in [ProcessStatus.RUNNING, ProcessStatus.UNKNOWN]:
                            # Process finished, but there might still be logs in queue
                            # Try to get remaining logs with short timeout
                            try:
                                while True:
                                    log_entry = process_info.log_queue.get_nowait()
                                    if log_entry is None:
                                        break
                                    log_file.write(log_entry)
                                    log_file.flush()
                            except Empty:
                                pass
                            break
                        continue
                        
        except Exception as e:
            logging.error(f"Error in log writer for process {process_info.process_id}: {e}")
            # Try to write error to file if possible
            try:
                with open(process_info.log_file_host, 'a') as log_file:
                    log_file.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] LOG WRITER ERROR: {str(e)}\n")
                    log_file.flush()
            except:
                pass
    
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
    
    def list_processes(self) -> List[HostProcessInfo]:
        """List all processes, optionally filtered by agent_id"""
        with self.lock:
            processes = list(self.processes.values())
            return processes
    
    def get_process_logs(self, process_id: str, lines: int = 100) -> str:
        """Get recent logs for a process"""
        with self.lock:
            if process_id not in self.processes:
                return ""
            
            process_info = self.processes[process_id]
            
            try:
                # First try to read from file
                if os.path.exists(process_info.log_file_host) and os.path.getsize(process_info.log_file_host) > 0:
                    with open(process_info.log_file_host, 'r') as f:
                        content = f.read()
                        if content.strip():  # File has content
                            lines_list = content.split('\n')
                            return '\n'.join(lines_list[-lines:]) if len(lines_list) > lines else content
                
                # If file is empty or doesn't exist, return in-memory logs
                if process_info.output_lines:
                    return '\n'.join(process_info.output_lines[-lines:])
                
                # If no logs available, return status info
                return f"Process {process_id} - Status: {process_info.status.value}, No output captured yet"
                
            except Exception as e:
                logging.error(f"Error reading logs for process {process_id}: {e}")
                # Return in-memory logs as fallback
                if process_info.output_lines:
                    return '\n'.join(process_info.output_lines[-lines:])
                return f"Error reading logs: {str(e)}"
    
    def wait_for_process(self, process_id: str, timeout: Optional[float] = None) -> bool:
        """Wait for a process to complete"""
        with self.lock:
            if process_id not in self.processes:
                return False
            process_info = self.processes[process_id]
        
        if process_info.process_thread:
            process_info.process_thread.join(timeout)
            return not process_info.process_thread.is_alive()
        else:
            # Synchronous process - already completed
            return True
    
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