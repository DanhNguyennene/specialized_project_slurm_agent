"""
MCP Client for SSE Transport

Simple HTTP client to call MCP tools via the SSE server.
"""
import aiohttp
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class MCPClient:
    """
    MCP Client using HTTP to call tools on SSE server.
    
    Usage:
        client = MCPClient("http://localhost:3002")
        await client.connect()
        result = await client.call_tool("squeue", {"user": "alice"})
        await client.disconnect()
    """
    
    def __init__(self, base_url: str = "http://localhost:3002"):
        self.base_url = base_url.rstrip("/")
        self.message_url = f"{self.base_url}/message"
        self._session: Optional[aiohttp.ClientSession] = None
        self._msg_id = 0
        self.connected = False
    
    async def connect(self) -> bool:
        """Initialize HTTP session and verify server."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        
        try:
            # Check health endpoint
            async with self._session.get(f"{self.base_url}/health") as resp:
                if resp.status == 200:
                    self.connected = True
                    logger.info(f"Connected to MCP server at {self.base_url}")
                    return True
        except Exception as e:
            logger.warning(f"Could not connect to MCP server: {e}")
        
        self.connected = False
        return False
    
    async def disconnect(self):
        """Close HTTP session."""
        if self._session:
            await self._session.close()
            self._session = None
        self.connected = False
    
    async def _send_message(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send JSON-RPC message to MCP server."""
        if self._session is None:
            await self.connect()
        
        self._msg_id += 1
        message = {
            "jsonrpc": "2.0",
            "id": self._msg_id,
            "method": method,
            "params": params or {}
        }
        
        try:
            async with self._session.post(
                self.message_url,
                json=message,
                headers={"Content-Type": "application/json"}
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    return {"error": f"HTTP {resp.status}"}
        except Exception as e:
            return {"error": str(e)}
    
    async def initialize(self) -> Dict[str, Any]:
        """Initialize MCP connection."""
        return await self._send_message("initialize")
    
    async def list_tools(self) -> list:
        """List available tools."""
        result = await self._send_message("tools/list")
        return result.get("result", {}).get("tools", [])
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any] = None) -> str:
        """
        Call an MCP tool.
        
        Args:
            tool_name: Name of the tool (squeue, sacct, etc.)
            arguments: Tool arguments
        
        Returns:
            Tool output as string
        """
        result = await self._send_message("tools/call", {
            "name": tool_name,
            "arguments": arguments or {}
        })
        
        # Extract content from MCP response
        if "result" in result:
            content = result["result"].get("content", [])
            if content and len(content) > 0:
                return content[0].get("text", "")
        
        if "error" in result:
            return f"Error: {result['error']}"
        
        return json.dumps(result)
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, *args):
        await self.disconnect()
