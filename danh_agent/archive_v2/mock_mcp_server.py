"""
Mock Slurm MCP Server for testing agent tool execution
Simulates Slurm cluster responses without needing actual cluster
"""
import asyncio
import websockets
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mock Slurm data
MOCK_JOBS = [
    {"job_id": "12345", "name": "test_job", "state": "RUNNING", "partition": "compute", "user": "testuser", "time": "00:15:23"},
    {"job_id": "12346", "name": "analysis", "state": "PENDING", "partition": "gpu", "user": "testuser", "time": "00:00:00"},
]

MOCK_NODES = [
    {"node": "node001", "state": "idle", "cpus": "32", "memory": "128GB"},
    {"node": "node002", "state": "allocated", "cpus": "32", "memory": "128GB"},
    {"node": "node003", "state": "idle", "cpus": "64", "memory": "256GB"},
]

MOCK_PARTITIONS = [
    {"partition": "compute", "state": "up", "nodes": "3", "time_limit": "24:00:00"},
    {"partition": "gpu", "state": "up", "nodes": "2", "time_limit": "12:00:00"},
]


def generate_response(tool_name, arguments):
    """Generate mock responses for Slurm commands"""
    
    if tool_name == "squeue_query":
        jobs = MOCK_JOBS.copy()
        if arguments.get("state"):
            jobs = [j for j in jobs if j["state"] == arguments["state"]]
        if arguments.get("user"):
            jobs = [j for j in jobs if j["user"] == arguments["user"]]
        
        return {
            "success": True,
            "jobs": jobs,
            "total_jobs": len(jobs)
        }
    
    elif tool_name == "sinfo_cluster":
        return {
            "success": True,
            "nodes": MOCK_NODES,
            "partitions": MOCK_PARTITIONS,
            "total_nodes": len(MOCK_NODES)
        }
    
    elif tool_name == "sbatch_submit":
        job_id = "12347"
        return {
            "success": True,
            "job_id": job_id,
            "message": f"Submitted batch job {job_id}",
            "script_path": arguments.get("script_path", "/tmp/job.sh")
        }
    
    elif tool_name == "create_batch_script":
        return {
            "success": True,
            "script_path": arguments.get("script_path"),
            "message": "Batch script created successfully"
        }
    
    elif tool_name == "scancel_job":
        job_id = arguments.get("job_id")
        return {
            "success": True,
            "job_id": job_id,
            "message": f"Job {job_id} cancelled successfully"
        }
    
    elif tool_name == "sacct_accounting":
        return {
            "success": True,
            "jobs": [
                {
                    "job_id": "12340",
                    "name": "completed_job",
                    "state": "COMPLETED",
                    "elapsed": "01:23:45",
                    "cpu_time": "05:35:00",
                    "memory": "45GB"
                }
            ]
        }
    
    elif tool_name == "scontrol_show":
        entity = arguments.get("entity")
        if entity == "job":
            return {
                "success": True,
                "entity": "job",
                "details": {
                    "JobId": "12345",
                    "JobName": "test_job",
                    "UserId": "testuser(1000)",
                    "GroupId": "testgroup(1000)",
                    "Partition": "compute",
                    "JobState": "RUNNING",
                    "NodeList": "node001",
                    "RunTime": "00:15:23",
                    "TimeLimit": "01:00:00"
                }
            }
        elif entity == "node":
            return {
                "success": True,
                "entity": "node",
                "details": MOCK_NODES[0]
            }
        else:
            return {
                "success": True,
                "entity": entity,
                "details": {"info": f"Mock {entity} details"}
            }
    
    elif tool_name == "srun_interactive":
        command = arguments.get("command", "echo test")
        return {
            "success": True,
            "stdout": f"Executing: {command}\nOutput: Mock execution successful",
            "stderr": "",
            "exit_code": 0
        }
    
    else:
        return {
            "success": True,
            "message": f"Mock response for {tool_name}",
            "arguments": arguments
        }


async def handle_client(websocket, path):
    """Handle WebSocket client connections"""
    logger.info(f"Client connected from {websocket.remote_address}")
    
    try:
        async for message in websocket:
            data = json.loads(message)
            logger.info(f"Received: {data.get('method')} (id: {data.get('id')})")
            
            # Handle initialization
            if data.get("method") == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": data.get("id"),
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {}
                        },
                        "serverInfo": {
                            "name": "mock-slurm-mcp-server",
                            "version": "1.0.0"
                        }
                    }
                }
                await websocket.send(json.dumps(response))
                logger.info("Sent initialization response")
            
            # Handle tool calls
            elif data.get("method") == "tools/call":
                params = data.get("params", {})
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                
                logger.info(f"Tool call: {tool_name} with args: {arguments}")
                
                # Generate mock response
                mock_result = generate_response(tool_name, arguments)
                
                response = {
                    "jsonrpc": "2.0",
                    "id": data.get("id"),
                    "result": [
                        {
                            "type": "text",
                            "text": json.dumps(mock_result)
                        }
                    ]
                }
                await websocket.send(json.dumps(response))
                logger.info(f"Sent tool response for {tool_name}")
            
            else:
                logger.warning(f"Unknown method: {data.get('method')}")
                response = {
                    "jsonrpc": "2.0",
                    "id": data.get("id"),
                    "error": {
                        "code": -32601,
                        "message": "Method not found"
                    }
                }
                await websocket.send(json.dumps(response))
    
    except websockets.exceptions.ConnectionClosed:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"Error handling client: {e}")


async def main():
    """Start the mock MCP server"""
    host = "localhost"
    port = 3005
    
    logger.info(f"Starting Mock Slurm MCP Server on ws://{host}:{port}")
    logger.info("This server simulates Slurm cluster responses for testing")
    
    async with websockets.serve(handle_client, host, port):
        logger.info(f"Server running on ws://{host}:{port}")
        logger.info("Press Ctrl+C to stop")
        await asyncio.Future()  # Run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nServer stopped")
