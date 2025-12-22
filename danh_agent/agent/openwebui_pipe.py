"""
OpenWebUI Pipe Function for Slurm Agent

This Pipe integrates directly with OpenWebUI and provides:
- Reasoning display (thinking process from qwen3-coder)
- Text-based confirmation for dangerous actions
- Real-time status updates via __event_emitter__
- The agent decides when to ask for confirmation

Architecture:
- Main Agent: qwen3-coder (reasoning/thinking)
- Sub-Agents: gpt-oss (tool execution)

Install: Copy this file to OpenWebUI's functions directory or paste in the UI.
"""
from pydantic import BaseModel, Field
from typing import Optional, AsyncGenerator, Union
import asyncio
import json
import logging

logger = logging.getLogger(__name__)


class Pipe:
    """Slurm Agent Pipe with Reasoning Display"""
    
    class Valves(BaseModel):
        """Configuration options for the Slurm Agent"""
        MCP_SERVER_URL: str = Field(
            default="http://localhost:3002",
            description="URL of the Slurm MCP server"
        )
        REASONING_MODEL: str = Field(
            default="qwen3-coder:latest",
            description="Main agent model for reasoning/thinking"
        )
        TOOL_MODEL: str = Field(
            default="gpt-oss:latest",
            description="Sub-agent model for tool execution"
        )
        OLLAMA_URL: str = Field(
            default="http://localhost:11434/v1",
            description="Ollama API URL"
        )
        SHOW_REASONING: bool = Field(
            default=True,
            description="Display the agent's thinking process"
        )
    
    def __init__(self):
        self.valves = self.Valves()
        self._agent_system = None
    
    async def _get_agent(self):
        """Lazy initialization of agent system"""
        if self._agent_system is None:
            from flow.multi_agent import SlurmMultiAgentSystem
            self._agent_system = SlurmMultiAgentSystem(
                reasoning_model=self.valves.REASONING_MODEL,
                tool_model=self.valves.TOOL_MODEL,
                base_url=self.valves.OLLAMA_URL,
                mcp_url=self.valves.MCP_SERVER_URL,
            )
        return self._agent_system
    
    async def pipe(
        self,
        body: dict,
        __user__: dict = None,
        __event_emitter__=None,
    ) -> Union[str, AsyncGenerator[str, None]]:
        """
        Main pipe function - processes user messages.
        
        The agent handles confirmation via text - when dangerous action is blocked,
        it asks the user to confirm. User says "yes" in next message to proceed.
        """
        messages = body.get("messages", [])
        if not messages:
            return "No message provided"
        
        user_message = messages[-1].get("content", "") if messages else ""
        session_id = __user__.get("id", "default") if __user__ else "default"
        
        # Get or create agent
        agent = await self._get_agent()
        agent.session_id = session_id  # Set session for this request
        
        # Stream mode
        if body.get("stream", False):
            return self._stream_response(
                user_message, messages, session_id, __event_emitter__
            )
        else:
            return await self._run_once(user_message, session_id, __event_emitter__)
    
    async def _stream_response(
        self,
        user_message: str,
        messages: list,
        session_id: str,
        __event_emitter__,
    ) -> AsyncGenerator[str, None]:
        """Stream response from agent with reasoning display"""
        
        agent = await self._get_agent()
        
        in_reasoning = False  # Track if we're in a thinking block
        reasoning_buffer = []  # Collect reasoning tokens
        
        async for event in agent.run_streaming(user_message, conversation_history=messages):
            event_type = event.get("type")
            
            # Status updates
            if event_type == "status":
                if __event_emitter__:
                    await __event_emitter__({
                        "type": "status",
                        "data": {"description": event.get("message", "")}
                    })
            
            # Agent switch
            elif event_type == "agent_switch":
                # End reasoning block if switching agents
                if in_reasoning and reasoning_buffer:
                    yield "\n</details>\n\n"
                    in_reasoning = False
                    reasoning_buffer = []
                
                if __event_emitter__:
                    await __event_emitter__({
                        "type": "status",
                        "data": {"description": event.get("message", "")}
                    })
            
            # Reasoning content (thinking process)
            elif event_type == "reasoning":
                if self.valves.SHOW_REASONING:
                    content = event.get("content", "")
                    agent_name = event.get("agent", "Agent")
                    
                    # Start a collapsible block for reasoning
                    if not in_reasoning:
                        in_reasoning = True
                        yield f"\n<details>\n<summary>💭 <b>{agent_name} thinking...</b></summary>\n\n```\n"
                    
                    reasoning_buffer.append(content)
                    yield content
            
            # Tool calls
            elif event_type == "tool_call":
                # End reasoning block before tool output
                if in_reasoning and reasoning_buffer:
                    yield "\n```\n</details>\n\n"
                    in_reasoning = False
                    reasoning_buffer = []
                
                if __event_emitter__:
                    await __event_emitter__({
                        "type": "status",
                        "data": {"description": f"🔧 {event.get('message', '')}"}
                    })
            
            # Tool output
            elif event_type == "tool_output":
                if __event_emitter__:
                    await __event_emitter__({
                        "type": "status",
                        "data": {"description": event.get("message", "")}
                    })
            
            # Confirmation required - agent will ask via text
            elif event_type == "confirmation_required":
                # End reasoning block
                if in_reasoning and reasoning_buffer:
                    yield "\n```\n</details>\n\n"
                    in_reasoning = False
                    reasoning_buffer = []
                # Let the agent's final answer handle the confirmation prompt
            
            # Final answer
            elif event_type == "final_answer":
                # End reasoning block before final answer
                if in_reasoning and reasoning_buffer:
                    yield "\n```\n</details>\n\n"
                    in_reasoning = False
                    reasoning_buffer = []
                
                yield event.get("message", "")
            
            # Error
            elif event_type == "error":
                if in_reasoning:
                    yield "\n```\n</details>\n\n"
                    in_reasoning = False
                yield f"\n\n❌ Error: {event.get('message', 'Unknown error')}"
            
            # Done
            elif event_type == "done":
                if in_reasoning:
                    yield "\n```\n</details>\n\n"
                return
    
    async def _run_once(
        self,
        user_message: str,
        session_id: str,
        __event_emitter__,
    ) -> str:
        """Non-streaming single run"""
        agent = await self._get_agent()
        result = await agent.run(user_message)
        return result.get("message", "No response")


# For testing outside OpenWebUI
if __name__ == "__main__":
    import asyncio
    
    async def test():
        pipe = Pipe()
        result = await pipe.pipe(
            body={
                "messages": [{"role": "user", "content": "show my jobs"}],
                "stream": False
            },
            __user__={"id": "test"},
        )
        print(result)
    
    asyncio.run(test())
