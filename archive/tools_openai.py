"""
Slurm tools converted to OpenAI function calling format
"""
import asyncio
import os
import websockets
import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

API_KEY = next(
    (value for key, value in os.environ.items() if key.startswith("SLURM_API_KEY_")),
    "changeme"
)
print(f"Using SLURM_API_KEY: {API_KEY[:4]}***{API_KEY[-4:]}")

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
                first_result = tool_result[0]
                
                if isinstance(first_result, dict):
                    text_content = first_result.get("text", "{}")
                    
                    if text_content.strip().startswith('{') or text_content.strip().startswith('['):
                        try:  
                            parsed_result = json.loads(text_content)
                            return parsed_result
                        except json.JSONDecodeError:
                            return {
                                "success": True,
                                "content": text_content
                            }
                    else:
                        return {
                            "success": True,
                            "content": text_content
                        }
                else:
                    return {
                        "success": True,
                        "content": str(first_result)
                    }
            else:
                return {
                    "error": "Empty or invalid response from server",
                    "raw_result": tool_result
                }
                
        except websockets.exceptions.ConnectionClosed:
            logging.warning(f"WebSocket connection closed for {self.ws_url}, attempting reconnect...")
            self._websocket = None
            self._initialized = False
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


# OpenAI function definitions
SLURM_FUNCTION_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "slurm_submit_job",
            "description": "Submit a batch job to Slurm cluster using sbatch. Use this to schedule computational jobs, run simulations, or execute batch processing tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "script_path": {
                        "type": "string",
                        "description": "Path to the batch script file"
                    },
                    "job_name": {
                        "type": "string",
                        "description": "Name for the job"
                    },
                    "partition": {
                        "type": "string",
                        "description": "Partition/queue to submit to"
                    },
                    "nodes": {
                        "type": "integer",
                        "description": "Number of nodes required"
                    },
                    "ntasks": {
                        "type": "integer",
                        "description": "Number of tasks/processes"
                    },
                    "cpus_per_task": {
                        "type": "integer",
                        "description": "CPUs per task"
                    },
                    "mem": {
                        "type": "string",
                        "description": "Memory requirement (e.g., '4G', '1024M')"
                    },
                    "time": {
                        "type": "string",
                        "description": "Time limit (e.g., '1:00:00', '30:00')"
                    },
                    "output": {
                        "type": "string",
                        "description": "Output file path"
                    },
                    "error": {
                        "type": "string",
                        "description": "Error file path"
                    },
                    "additional_args": {
                        "type": "string",
                        "description": "Additional sbatch arguments as string"
                    }
                },
                "required": ["script_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "slurm_query_queue",
            "description": "Query job queue information using squeue. Use this to check job status, monitor queue, or get information about running/pending jobs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user": {
                        "type": "string",
                        "description": "Filter by username"
                    },
                    "job_id": {
                        "type": "string",
                        "description": "Filter by specific job ID"
                    },
                    "partition": {
                        "type": "string",
                        "description": "Filter by partition"
                    },
                    "state": {
                        "type": "string",
                        "description": "Filter by job state (PENDING, RUNNING, COMPLETED, etc.)"
                    },
                    "format_string": {
                        "type": "string",
                        "description": "Custom format string for output"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "slurm_cancel_job",
            "description": "Cancel Slurm jobs using scancel. Use this to stop running jobs, cancel pending jobs, or manage job lifecycle.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Job ID to cancel"
                    },
                    "user": {
                        "type": "string",
                        "description": "Cancel jobs for specific user"
                    },
                    "partition": {
                        "type": "string",
                        "description": "Cancel jobs in specific partition"
                    },
                    "state": {
                        "type": "string",
                        "description": "Cancel jobs in specific state"
                    },
                    "signal": {
                        "type": "string",
                        "description": "Signal to send to job (default: SIGTERM)"
                    }
                },
                "required": ["job_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "slurm_cluster_info",
            "description": "Get cluster/partition information using sinfo. Use this to check cluster status, available resources, node states, or partition information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "partition": {
                        "type": "string",
                        "description": "Filter by specific partition"
                    },
                    "nodes": {
                        "type": "string",
                        "description": "Filter by specific nodes"
                    },
                    "format_string": {
                        "type": "string",
                        "description": "Custom format string for output"
                    },
                    "summarize": {
                        "type": "boolean",
                        "description": "Show summary information"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "slurm_job_accounting",
            "description": "Get job accounting information using sacct. Use this to check completed jobs, resource usage, job statistics, or historical job information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Filter by specific job ID"
                    },
                    "user": {
                        "type": "string",
                        "description": "Filter by username"
                    },
                    "start_time": {
                        "type": "string",
                        "description": "Start time for query (format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"
                    },
                    "end_time": {
                        "type": "string",
                        "description": "End time for query"
                    },
                    "format_string": {
                        "type": "string",
                        "description": "Custom format string for output"
                    },
                    "state": {
                        "type": "string",
                        "description": "Filter by job state"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "slurm_show_details",
            "description": "Get detailed information using scontrol show. Use this to get comprehensive details about jobs, nodes, partitions, or other Slurm entities.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {
                        "type": "string",
                        "description": "Type of entity (job, node, partition, reservation, etc.)"
                    },
                    "name": {
                        "type": "string",
                        "description": "Specific name/ID to show (optional, shows all if not specified)"
                    }
                },
                "required": ["entity"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "slurm_run_interactive",
            "description": "Execute interactive command on compute nodes using srun. Use this for running commands directly on compute nodes, testing, or quick computations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Command to execute"
                    },
                    "nodes": {
                        "type": "integer",
                        "description": "Number of nodes"
                    },
                    "ntasks": {
                        "type": "integer",
                        "description": "Number of tasks"
                    },
                    "cpus_per_task": {
                        "type": "integer",
                        "description": "CPUs per task"
                    },
                    "mem": {
                        "type": "string",
                        "description": "Memory requirement"
                    },
                    "time": {
                        "type": "string",
                        "description": "Time limit"
                    },
                    "partition": {
                        "type": "string",
                        "description": "Partition to use"
                    },
                    "additional_args": {
                        "type": "string",
                        "description": "Additional srun arguments"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Command timeout in seconds"
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "slurm_create_script",
            "description": "Create a Slurm batch script file. Use this to generate properly formatted batch scripts for job submission.",
            "parameters": {
                "type": "object",
                "properties": {
                    "script_path": {
                        "type": "string",
                        "description": "Where to save the script"
                    },
                    "command": {
                        "type": "string",
                        "description": "Main command to execute"
                    },
                    "job_name": {
                        "type": "string",
                        "description": "Job name"
                    },
                    "partition": {
                        "type": "string",
                        "description": "Partition to use"
                    },
                    "nodes": {
                        "type": "integer",
                        "description": "Number of nodes"
                    },
                    "ntasks": {
                        "type": "integer",
                        "description": "Number of tasks"
                    },
                    "cpus_per_task": {
                        "type": "integer",
                        "description": "CPUs per task"
                    },
                    "mem": {
                        "type": "string",
                        "description": "Memory requirement"
                    },
                    "time": {
                        "type": "string",
                        "description": "Time limit"
                    },
                    "output": {
                        "type": "string",
                        "description": "Output file path"
                    },
                    "error": {
                        "type": "string",
                        "description": "Error file path"
                    },
                    "email": {
                        "type": "string",
                        "description": "Email address for notifications"
                    },
                    "email_type": {
                        "type": "string",
                        "description": "Email notification types (BEGIN, END, FAIL, ALL)"
                    },
                    "modules": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of modules to load"
                    },
                    "environment_vars": {
                        "type": "object",
                        "description": "Dictionary of environment variables to set"
                    }
                },
                "required": ["script_path", "command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "slurm_test_connection",
            "description": "Test connection to the Slurm cluster and verify MCP server is working.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
]


# Tool execution handlers
class SlurmToolExecutor:
    """Execute Slurm tools with OpenAI function calling"""
    
    def __init__(self, cluster_ip: str, cluster_port: int, api_key: Optional[str] = API_KEY):
        self.cluster_ip = cluster_ip
        self.cluster_port = cluster_port
        self.api_key = api_key
    
    async def execute_function(self, function_name: str, arguments: Dict[str, Any]) -> str:
        """Execute a Slurm function and return JSON string result"""
        try:
            if function_name == "slurm_submit_job":
                return await self._submit_job(arguments)
            elif function_name == "slurm_query_queue":
                return await self._query_queue(arguments)
            elif function_name == "slurm_cancel_job":
                return await self._cancel_job(arguments)
            elif function_name == "slurm_cluster_info":
                return await self._cluster_info(arguments)
            elif function_name == "slurm_job_accounting":
                return await self._job_accounting(arguments)
            elif function_name == "slurm_show_details":
                return await self._show_details(arguments)
            elif function_name == "slurm_run_interactive":
                return await self._run_interactive(arguments)
            elif function_name == "slurm_create_script":
                return await self._create_script(arguments)
            elif function_name == "slurm_test_connection":
                return await self._test_connection(arguments)
            else:
                return json.dumps({"error": f"Unknown function: {function_name}"})
        except Exception as e:
            return json.dumps({"error": f"Function execution failed: {str(e)}"})
    
    async def _submit_job(self, args: Dict[str, Any]) -> str:
        mcp = await slurm_connection_manager.get_connection(self.cluster_ip, self.cluster_port, self.api_key)
        result = await mcp.call_tool("sbatch_submit", args)
        return json.dumps(result, indent=2)
    
    async def _query_queue(self, args: Dict[str, Any]) -> str:
        mcp = await slurm_connection_manager.get_connection(self.cluster_ip, self.cluster_port, self.api_key)
        result = await mcp.call_tool("squeue_query", args)
        return json.dumps(result, indent=2)
    
    async def _cancel_job(self, args: Dict[str, Any]) -> str:
        mcp = await slurm_connection_manager.get_connection(self.cluster_ip, self.cluster_port, self.api_key)
        result = await mcp.call_tool("scancel_job", args)
        return json.dumps(result, indent=2)
    
    async def _cluster_info(self, args: Dict[str, Any]) -> str:
        mcp = await slurm_connection_manager.get_connection(self.cluster_ip, self.cluster_port, self.api_key)
        args.setdefault("summarize", False)
        result = await mcp.call_tool("sinfo_cluster", args)
        return json.dumps(result, indent=2)
    
    async def _job_accounting(self, args: Dict[str, Any]) -> str:
        mcp = await slurm_connection_manager.get_connection(self.cluster_ip, self.cluster_port, self.api_key)
        result = await mcp.call_tool("sacct_accounting", args)
        return json.dumps(result, indent=2)
    
    async def _show_details(self, args: Dict[str, Any]) -> str:
        mcp = await slurm_connection_manager.get_connection(self.cluster_ip, self.cluster_port, self.api_key)
        result = await mcp.call_tool("scontrol_show", args)
        return json.dumps(result, indent=2)
    
    async def _run_interactive(self, args: Dict[str, Any]) -> str:
        mcp = await slurm_connection_manager.get_connection(self.cluster_ip, self.cluster_port, self.api_key)
        args.setdefault("timeout", 300)
        result = await mcp.call_tool("srun_interactive", args)
        
        # Truncate output if too long
        if isinstance(result, dict):
            if "stdout" in result and isinstance(result["stdout"], str):
                result["stdout"] = result["stdout"][:2000]
            if "stderr" in result and isinstance(result["stderr"], str):
                result["stderr"] = result["stderr"][:2000]
        
        return json.dumps(result, indent=2)
    
    async def _create_script(self, args: Dict[str, Any]) -> str:
        mcp = await slurm_connection_manager.get_connection(self.cluster_ip, self.cluster_port, self.api_key)
        result = await mcp.call_tool("create_batch_script", args)
        return json.dumps(result, indent=2)
    
    async def _test_connection(self, args: Dict[str, Any]) -> str:
        result = await slurm_connection_manager.test_connection(self.cluster_ip, self.cluster_port, self.api_key)
        return json.dumps(result, indent=2)
