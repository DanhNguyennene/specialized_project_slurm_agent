import asyncio
import os
import websockets
import json
import logging
from typing import Dict, Any, List, Optional, Annotated, Union
from dataclasses import dataclass
from datetime import datetime, timezone
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool, InjectedToolArg
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.language_models import BaseChatModel
import functools
from contextvars import ContextVar
import os

API_KEY = next(
    (value for key, value in os.environ.items() if key.startswith("SLURM_API_KEY_")),
    "changeme"
)
print(f"Using SLURM_API_KEY: {API_KEY[:4]}***{API_KEY[-4:]}")
UTC = timezone.utc

logger = logging.getLogger(__name__)


class SlurmMCPConnection:
    """MCP connection manager for Slurm clusters - supports multiple instances with different IPs"""
    
    def __init__(self, cluster_ip: str = "10.1.1.2", cluster_port: int = 32222, api_key: Optional[str] = API_KEY):
        self.cluster_ip = cluster_ip
        self.cluster_port = cluster_port
        self.api_key = api_key
        self.ws_url = f"ws://{cluster_ip}:{cluster_port}"
        self._websocket = None
        self._message_id = 1
        self._initialized = False
    
    async def connect(self):
        self.ws_url = f"ws://{self.cluster_ip}:{self.cluster_port}"
        print(f"Connecting to Slurm MCP server at {self.ws_url}")
        if self._websocket is None:
            try:
                print(f"Connecting to {self.ws_url}...")
                self._websocket = await websockets.connect(
                    self.ws_url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=10
                )
                logging.info(f"Connected to Slurm MCP server at {self.ws_url}")
                
                # Initialize the connection
                if not self._initialized:
                    await self._initialize_connection()
                    
            except Exception as e:
                logging.error(f"Failed to connect to {self.ws_url}: {e}")
                raise
    
    async def _initialize_connection(self):
        """Initialize the MCP connection"""
        try:
            init_message = {
                "jsonrpc": "2.0",
                "id": self._message_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "slurm-agent-client",
                        "version": "1.0.0"
                    }
                }
            }
            if self.api_key:
                init_message["params"]["auth"] = {
                    "type": "api_key",
                    "key": self.api_key
                }
            self._message_id += 1
            await self._websocket.send(json.dumps(init_message))
            response = await self._websocket.recv()
            result = json.loads(response)
            
            if "error" in result:
                raise Exception(f"Initialization failed: {result['error']['message']}")
            
            logging.info(f"Slurm MCP connection initialized successfully for {self.ws_url}")
            self._initialized = True
            
        except Exception as e:
            logging.error(f"Failed to initialize Slurm MCP connection: {e}")
            raise
    
    async def disconnect(self):
        if self._websocket is not None:
            try:
                await self._websocket.close()
            except Exception as e:
                logging.warning(f"Error closing websocket: {e}")
            finally:
                self._websocket = None
                self._initialized = False
                logging.info(f"Disconnected from Slurm MCP server at {self.ws_url}")
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if self._websocket is None:
            await self.connect()
        
        try:
            message = {
                "jsonrpc": "2.0",
                "id": self._message_id,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments}
            }
            self._message_id += 1
            
            logging.debug(f"Sending tool call to {self.ws_url}: {tool_name}")
            await self._websocket.send(json.dumps(message))
            
            response = await self._websocket.recv()
            result = json.loads(response)
            
            logging.debug(f"Received response from {self.ws_url}: {result}")
            
            if "error" in result:
                error_msg = result["error"].get("message", "Unknown error")
                logging.error(f"Tool call error from {self.ws_url}: {error_msg}")
                return {"error": error_msg}
            
            # Handle the tool result properly
            tool_result = result.get("result", [])
            
            if isinstance(tool_result, list) and len(tool_result) > 0:
                # Get the first result item
                first_result = tool_result[0]
                
                if isinstance(first_result, dict):
                    # Try to get text content
                    text_content = first_result.get("text", "{}")
                    
                    # Try to parse as JSON if it looks like JSON
                    if text_content.strip().startswith('{') or text_content.strip().startswith('['):
                        try:  
                            parsed_result = json.loads(text_content)
                            return parsed_result
                        except json.JSONDecodeError:
                            # If JSON parsing fails, return the raw text
                            return {
                                "success": True,
                                "content": text_content
                            }
                    else:
                        # Return non-JSON text content
                        return {
                            "success": True,
                            "content": text_content
                        }
                else:
                    # Handle non-dict result items
                    return {
                        "success": True,
                        "content": str(first_result)
                    }
            else:
                # Empty or invalid result
                return {
                    "error": "Empty or invalid response from server",
                    "raw_result": tool_result
                }
                
        except websockets.exceptions.ConnectionClosed:
            logging.warning(f"WebSocket connection closed for {self.ws_url}, attempting reconnect...")
            self._websocket = None
            self._initialized = False
            # Try once more after reconnecting
            try:
                await self.connect()
                return await self.call_tool(tool_name, arguments)
            except Exception as e:
                return {"error": f"Reconnection failed: {str(e)}", "cluster_info": f"{self.cluster_ip}:{self.cluster_port}"}
                
        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse JSON response from {self.ws_url}: {e}")
            return {"error": f"Invalid JSON response: {str(e)}", "cluster_info": f"{self.cluster_ip}:{self.cluster_port}"}
            
        except Exception as e:
            logging.error(f"Tool call failed for {self.ws_url}: {e}")
            return {"error": f"Request failed: {str(e)}", "cluster_info": f"{self.cluster_ip}:{self.cluster_port}"}


# Connection manager for multiple Slurm clusters
class SlurmMCPConnectionManager:
    """Manages multiple MCP connections for different Slurm clusters"""
    
    def __init__(self):
        self.connections: Dict[str, SlurmMCPConnection] = {}
    
    async def get_connection(self, cluster_ip: str, cluster_port: int = 3001, api_key: Optional[str] = API_KEY) -> SlurmMCPConnection:
        """Get or create connection for a Slurm cluster"""
        key = f"{cluster_ip}:{cluster_port}"
        if key not in self.connections:
            self.connections[key] = SlurmMCPConnection(cluster_ip, cluster_port, api_key)
        return self.connections[key]
    async def disconnect_all(self):
        """Disconnect all connections"""
        for connection in self.connections.values():
            await connection.disconnect()
        self.connections.clear()

    async def test_connection(self, cluster_ip: str, cluster_port: int = 3001, api_key: Optional[str] = API_KEY) -> Dict[str, Any]:
        """Test connection to a Slurm cluster"""
        try:
            mcp = await self.get_connection(cluster_ip, cluster_port, api_key)
            result = await mcp.call_tool("sinfo_cluster", {})
            
            if "error" in result:
                return {
                    "success": False,
                    "error": result["error"]
                }
            else:
                return {
                    "success": True,
                    "message": "Connection test successful"
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }


# Global connection manager
slurm_connection_manager = SlurmMCPConnectionManager()


# Slurm tool functions that use context
@tool()
async def slurm_submit_job(
    cluster_ip: Annotated[str, InjectedToolArg],
    cluster_port: Annotated[int, InjectedToolArg],
    script_path: str,
    api_key: Annotated[Optional[str], InjectedToolArg]=API_KEY,
    job_name: Optional[str] = None,
    partition: Optional[str] = None,
    nodes: Optional[int] = None,
    ntasks: Optional[int] = None,
    cpus_per_task: Optional[int] = None,
    mem: Optional[str] = None,
    time: Optional[str] = None,
    output: Optional[str] = None,
    error: Optional[str] = None,
    additional_args: Optional[str] = None
) -> str:
    """Submit a batch job to Slurm cluster using sbatch. Use this to schedule computational 
    jobs, run simulations, or execute batch processing tasks.
    
    Args:
        script_path: Path to the batch script file
        job_name: Name for the job
        partition: Partition/queue to submit to
        nodes: Number of nodes required
        ntasks: Number of tasks/processes
        cpus_per_task: CPUs per task
        mem: Memory requirement (e.g., "4G", "1024M")
        time: Time limit (e.g., "1:00:00", "30:00")
        output: Output file path
        error: Error file path
        additional_args: Additional sbatch arguments as string
    """
    try:
        mcp = await slurm_connection_manager.get_connection(cluster_ip, cluster_port, api_key)
        
        args = {"script_path": script_path}
        if job_name:
            args["job_name"] = job_name
        if partition:
            args["partition"] = partition
        if nodes:
            args["nodes"] = nodes
        if ntasks:
            args["ntasks"] = ntasks
        if cpus_per_task:
            args["cpus_per_task"] = cpus_per_task
        if mem:
            args["mem"] = mem
        if time:
            args["time"] = time
        if output:
            args["output"] = output
        if error:
            args["error"] = error
        if additional_args:
            args["additional_args"] = additional_args
        
        result = await mcp.call_tool("sbatch_submit", args)
        return json.dumps(result, indent=2)
        
    except Exception as e:
        error_result = {
            "error": f"Failed to submit job: {str(e)}",
            "script_path": script_path
        }
        return json.dumps(error_result, indent=2)


@tool()
async def slurm_query_queue(
    cluster_ip: Annotated[str, InjectedToolArg],
    cluster_port: Annotated[int, InjectedToolArg],
    api_key: Annotated[Optional[str], InjectedToolArg] = API_KEY,
    user: Optional[str] = None,
    job_id: Optional[str] = None,
    partition: Optional[str] = None,
    state: Optional[str] = None,
    format_string: Optional[str] = None
) -> str:
    """Query job queue information using squeue. Use this to check job status,
    monitor queue, or get information about running/pending jobs.
    
    Args:
        user: Filter by username
        job_id: Filter by specific job ID
        partition: Filter by partition
        state: Filter by job state (PENDING, RUNNING, COMPLETED, etc.)
        format_string: Custom format string for output
    """
    try:
        mcp = await slurm_connection_manager.get_connection(cluster_ip, cluster_port, api_key)
        
        args = {}
        if user:
            args["user"] = user
        if job_id:
            args["job_id"] = job_id
        if partition:
            args["partition"] = partition
        if state:
            args["state"] = state
        if format_string:
            args["format_string"] = format_string
        
        result = await mcp.call_tool("squeue_query", args)
        return json.dumps(result, indent=2)
        
    except Exception as e:
        error_result = {
            "error": f"Failed to query queue: {str(e)}"
        }
        return json.dumps(error_result, indent=2)


@tool()
async def slurm_cancel_job(
    cluster_ip: Annotated[str, InjectedToolArg],
    cluster_port: Annotated[int, InjectedToolArg],
    job_id: str,
    api_key: Annotated[Optional[str], InjectedToolArg] = API_KEY,
    user: Optional[str] = None,
    partition: Optional[str] = None,
    state: Optional[str] = None,
    signal: Optional[str] = None
) -> str:
    """Cancel Slurm jobs using scancel. Use this to stop running jobs,
    cancel pending jobs, or manage job lifecycle.
    
    Args:
        job_id: Job ID to cancel
        user: Cancel jobs for specific user
        partition: Cancel jobs in specific partition
        state: Cancel jobs in specific state
        signal: Signal to send to job (default: SIGTERM)
    """
    try:
        mcp = await slurm_connection_manager.get_connection(cluster_ip, cluster_port, api_key)
        
        args = {"job_id": job_id}
        if user:
            args["user"] = user
        if partition:
            args["partition"] = partition
        if state:
            args["state"] = state
        if signal:
            args["signal"] = signal
        
        result = await mcp.call_tool("scancel_job", args)
        return json.dumps(result, indent=2)
        
    except Exception as e:
        error_result = {
            "error": f"Failed to cancel job: {str(e)}",
            "job_id": job_id
        }
        return json.dumps(error_result, indent=2)


@tool()
async def slurm_cluster_info(
    cluster_ip: Annotated[str, InjectedToolArg],
    cluster_port: Annotated[int, InjectedToolArg],
    api_key: Annotated[Optional[str], InjectedToolArg] = API_KEY,
    partition: Optional[str] = None,
    nodes: Optional[str] = None,
    format_string: Optional[str] = None,
    summarize: bool = False
) -> str:
    """Get cluster/partition information using sinfo. Use this to check cluster status,
    available resources, node states, or partition information.
    
    Args:
        partition: Filter by specific partition
        nodes: Filter by specific nodes
        format_string: Custom format string for output
        summarize: Show summary information
    """
    try:
        mcp = await slurm_connection_manager.get_connection(cluster_ip, cluster_port, api_key)
        
        args = {"summarize": summarize}
        if partition:
            args["partition"] = partition
        if nodes:
            args["nodes"] = nodes
        if format_string:
            args["format_string"] = format_string
        
        result = await mcp.call_tool("sinfo_cluster", args)
        return json.dumps(result, indent=2)
        
    except Exception as e:
        error_result = {
            "error": f"Failed to get cluster info: {str(e)}"
        }
        return json.dumps(error_result, indent=2)


@tool()
async def slurm_job_accounting(
    cluster_ip: Annotated[str, InjectedToolArg],
    cluster_port: Annotated[int, InjectedToolArg],
    api_key: Annotated[Optional[str], InjectedToolArg] = API_KEY,
    job_id: Optional[str] = None,
    user: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    format_string: Optional[str] = None,
    state: Optional[str] = None
) -> str:
    """Get job accounting information using sacct. Use this to check completed jobs,
    resource usage, job statistics, or historical job information.
    
    Args:
        job_id: Filter by specific job ID
        user: Filter by username
        start_time: Start time for query (format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
        end_time: End time for query
        format_string: Custom format string for output
        state: Filter by job state
    """
    try:
        mcp = await slurm_connection_manager.get_connection(cluster_ip, cluster_port, api_key)
        
        args = {}
        if job_id:
            args["job_id"] = job_id
        if user:
            args["user"] = user
        if start_time:
            args["start_time"] = start_time
        if end_time:
            args["end_time"] = end_time
        if format_string:
            args["format_string"] = format_string
        if state:
            args["state"] = state
        
        result = await mcp.call_tool("sacct_accounting", args)
        return json.dumps(result, indent=2)
        
    except Exception as e:
        error_result = {
            "error": f"Failed to get accounting info: {str(e)}"
        }
        return json.dumps(error_result, indent=2)


@tool()
async def slurm_show_details(
    cluster_ip: Annotated[str, InjectedToolArg],
    cluster_port: Annotated[int, InjectedToolArg],
    entity: str,
    api_key: Annotated[Optional[str], InjectedToolArg] = API_KEY,
    name: Optional[str] = None
) -> str:
    """Get detailed information using scontrol show. Use this to get comprehensive
    details about jobs, nodes, partitions, or other Slurm entities.
    
    Args:
        entity: Type of entity (job, node, partition, reservation, etc.)
        name: Specific name/ID to show (optional, shows all if not specified)
    """
    try:
        mcp = await slurm_connection_manager.get_connection(cluster_ip, cluster_port, api_key)
        
        args = {"entity": entity}
        if name:
            args["name"] = name
        
        result = await mcp.call_tool("scontrol_show", args)
        return json.dumps(result, indent=2)
        
    except Exception as e:
        error_result = {
            "error": f"Failed to show details: {str(e)}",
            "entity": entity
        }
        return json.dumps(error_result, indent=2)


@tool()
async def slurm_run_interactive(
    cluster_ip: Annotated[str, InjectedToolArg],
    cluster_port: Annotated[int, InjectedToolArg],
    command: str,
    api_key: Annotated[Optional[str], InjectedToolArg] = API_KEY,
    nodes: Optional[int] = None,
    ntasks: Optional[int] = None,
    cpus_per_task: Optional[int] = None,
    mem: Optional[str] = None,
    time: Optional[str] = None,
    partition: Optional[str] = None,
    additional_args: Optional[str] = None,
    timeout: int = 300
) -> str:
    """Execute interactive command on compute nodes using srun. Use this for
    running commands directly on compute nodes, testing, or quick computations.
    
    Args:
        command: Command to execute
        nodes: Number of nodes
        ntasks: Number of tasks
        cpus_per_task: CPUs per task
        mem: Memory requirement
        time: Time limit
        partition: Partition to use
        additional_args: Additional srun arguments
        timeout: Command timeout in seconds
    """
    try:
        mcp = await slurm_connection_manager.get_connection(cluster_ip, cluster_port, api_key)
        
        args = {"command": command, "timeout": timeout}
        if nodes:
            args["nodes"] = nodes
        if ntasks:
            args["ntasks"] = ntasks
        if cpus_per_task:
            args["cpus_per_task"] = cpus_per_task
        if mem:
            args["mem"] = mem
        if time:
            args["time"] = time
        if partition:
            args["partition"] = partition
        if additional_args:
            args["additional_args"] = additional_args
        
        result = await mcp.call_tool("srun_interactive", args)
        
        # Truncate output if too long
        if isinstance(result, dict):
            if "stdout" in result and isinstance(result["stdout"], str):
                result["stdout"] = result["stdout"][:2000]
            if "stderr" in result and isinstance(result["stderr"], str):
                result["stderr"] = result["stderr"][:2000]
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        error_result = {
            "error": f"Failed to run interactive command: {str(e)}",
            "command": command
        }
        return json.dumps(error_result, indent=2)


@tool()
async def slurm_create_script(
    cluster_ip: Annotated[str, InjectedToolArg],
    cluster_port: Annotated[int, InjectedToolArg],
    script_path: str,
    command: str,
    api_key: Annotated[Optional[str], InjectedToolArg] = API_KEY,
    job_name: Optional[str] = None,
    partition: Optional[str] = None,
    nodes: Optional[int] = None,
    ntasks: Optional[int] = None,
    cpus_per_task: Optional[int] = None,
    mem: Optional[str] = None,
    time: Optional[str] = None,
    output: Optional[str] = None,
    error: Optional[str] = None,
    email: Optional[str] = None,
    email_type: Optional[str] = None,
    modules: Optional[List[str]] = None,
    environment_vars: Optional[Dict[str, str]] = None
) -> str:
    """Create a Slurm batch script file. Use this to generate properly formatted
    batch scripts for job submission.
    
    Args:
        script_path: Where to save the script
        command: Main command to execute
        job_name: Job name
        partition: Partition to use
        nodes: Number of nodes
        ntasks: Number of tasks
        cpus_per_task: CPUs per task
        mem: Memory requirement
        time: Time limit
        output: Output file path
        error: Error file path
        email: Email address for notifications
        email_type: Email notification types (BEGIN, END, FAIL, ALL)
        modules: List of modules to load
        environment_vars: Dictionary of environment variables to set
    """
    try:
        mcp = await slurm_connection_manager.get_connection(cluster_ip, cluster_port, api_key)
        
        args = {
            "script_path": script_path,
            "command": command
        }
        if job_name:
            args["job_name"] = job_name
        if partition:
            args["partition"] = partition
        if nodes:
            args["nodes"] = nodes
        if ntasks:
            args["ntasks"] = ntasks
        if cpus_per_task:
            args["cpus_per_task"] = cpus_per_task
        if mem:
            args["mem"] = mem
        if time:
            args["time"] = time
        if output:
            args["output"] = output
        if error:
            args["error"] = error
        if email:
            args["email"] = email
        if email_type:
            args["email_type"] = email_type
        if modules:
            args["modules"] = modules
        if environment_vars:
            args["environment_vars"] = environment_vars
        
        result = await mcp.call_tool("create_batch_script", args)
        return json.dumps(result, indent=2)
        
    except Exception as e:
        error_result = {
            "error": f"Failed to create batch script: {str(e)}",
            "script_path": script_path
        }
        return json.dumps(error_result, indent=2)


@tool()
async def slurm_test_connection(
    cluster_ip: Annotated[str, InjectedToolArg],
    cluster_port: Annotated[int, InjectedToolArg],
    api_key: Annotated[Optional[str], InjectedToolArg] = API_KEY
) -> str:
    """Test connection to the Slurm cluster and verify MCP server is working."""
    result = await slurm_connection_manager.test_connection(cluster_ip, cluster_port, api_key)
    return json.dumps(result, indent=2)


# List of all Slurm tools
SLURM_TOOLS = [
    slurm_submit_job,
    slurm_query_queue,
    slurm_cancel_job,
    slurm_cluster_info,
    slurm_job_accounting,
    slurm_show_details,
    slurm_run_interactive,
    slurm_create_script,
    slurm_test_connection
]

