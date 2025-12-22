"""
Multi-Agent Slurm System using OpenAI Agents SDK Handoffs + MCP

Architecture:
- Triage Agent (main): Routes requests to specialists
- Analysis Agent: Handles read-only cluster queries
- Action Agent: Handles job management

Uses SDK handoffs for automatic agent routing.
Uses SDK MCP integration for native tool execution.
"""
import logging
from typing import Optional, AsyncGenerator, Dict, Any, Set
import json

from agents import Agent, Runner
from agents.mcp import MCPServerSse, ToolFilterContext
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from agents.model_settings import ModelSettings
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# ============ Tool Filtering ============
# Analysis Agent: Read-only tools
ANALYSIS_TOOL_NAMES: Set[str] = {"squeue", "sacct", "sinfo", "scontrol_show", "run_analysis"}
# Action Agent: Management tools + read-only for context before acting
ACTION_TOOL_NAMES: Set[str] = {
    "sbatch", "scancel",  # Submit/cancel
    "scontrol_hold", "scontrol_release", "scontrol_update",  # Job control
    "squeue", "sacct", "scontrol_show"  # Read-only for context
}
# Dangerous tools that require confirmation
DANGEROUS_TOOLS: Set[str] = {"scancel", "scontrol_hold", "scontrol_release", "scontrol_update"}


# Pending confirmation storage
from dataclasses import dataclass
from typing import Callable, Awaitable

@dataclass
class PendingConfirmation:
    """Stores a pending dangerous action awaiting user confirmation."""
    tool_name: str
    arguments: Dict[str, Any]
    description: str  # Human-readable description of what will happen

# MCP Server URL
MCP_SERVER_URL = "http://localhost:3002"


# ============ Dynamic Tool Filter ============
def create_agent_tool_filter():
    """
    Create a dynamic tool filter that limits tools based on the current agent.
    
    The SDK calls this filter with ToolFilterContext which includes the agent
    making the request, allowing us to expose different tools to different agents.
    """
    async def agent_aware_filter(context: ToolFilterContext, tool) -> bool:
        agent_name = context.agent.name if context.agent else "unknown"
        tool_name = tool.name
        
        # Triage Agent: No tools (only handoffs)
        if agent_name == "Slurm Assistant":
            return False
        
        # Analysis Agent: Read-only tools only
        if agent_name == "Analysis Agent":
            allowed = tool_name in ANALYSIS_TOOL_NAMES
            if allowed:
                logger.debug(f"Analysis Agent: allowing tool '{tool_name}'")
            return allowed
        
        # Action Agent: Management tools + read-only for context
        if agent_name == "Action Agent":
            allowed = tool_name in ACTION_TOOL_NAMES
            if allowed:
                logger.debug(f"Action Agent: allowing tool '{tool_name}'")
            return allowed
        
        # Unknown agent: deny all tools
        logger.warning(f"Unknown agent '{agent_name}' requesting tool '{tool_name}' - denied")
        return False
    
    return agent_aware_filter


# ============ Model Configuration ============
def create_ollama_model(model_name: str = "gpt-oss:latest") -> OpenAIChatCompletionsModel:
    """Create Ollama-compatible model."""
    client = AsyncOpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
    return OpenAIChatCompletionsModel(model=model_name, openai_client=client)


# Model settings for tool-calling agents
STRICT_JSON_MODEL_SETTINGS = ModelSettings(
    temperature=0.1,              # Low temperature for accurate JSON
)


# ============ Non-OpenAI SDK Prompt Prefix ============

NON_OPENAI_SDK_PREFIX = """## STRICT PARAMETER RULES
- Parameters must be exact values from the schema enum, not invented
- Only use values explicitly mentioned in the conversation (job IDs, usernames)
- Never put natural language or questions into parameters
- Leave parameters null if no specific value is known
- Do not invent IDs, names, or values

## ReAct STRATEGY - NEVER REPEAT
- NEVER repeat the same action twice - if it didn't give enough info, try a DIFFERENT action
- Escalate from general to specific: run_analysis -> sacct with job_id -> scontrol_show_job
- Each step must provide NEW information not seen before
"""


# ============ Agent Instructions ============

ANALYSIS_AGENT_INSTRUCTIONS = f"""{RECOMMENDED_PROMPT_PREFIX}
{NON_OPENAI_SDK_PREFIX}

You are the Slurm Analysis Agent. You handle READ-ONLY queries about the cluster.

## AVAILABLE ANALYSIS SCRIPTS (use run_analysis tool):
- analyze_my_jobs: Overview of YOUR jobs (running, pending, recent)
- analyze_failed_jobs: List all failed jobs with exit codes
- analyze_queue: Current queue state with wait times
- analyze_resources: Cluster resource utilization
- analyze_partition: Partition availability and limits

## TOOL SELECTION STRATEGY (choose ONE at a time):
1. run_analysis: ALWAYS START HERE with an analysis script name (e.g., analyze_failed_jobs)
2. sacct: Use ONLY when you have a specific job_id from previous output
3. scontrol_show: Deep dive into ONE job's full configuration (use job_id from output)
4. squeue: Only for real-time queue snapshot
5. sinfo: Only for node/partition hardware status
5. sinfo: Node/partition status only

IMPORTANT: After run_analysis shows failed jobs with IDs, use sacct with those specific job_ids!

After gathering information, summarize your findings clearly for the user.

## HANDOFF TO ACTION AGENT
If the user asks you to FIX, CANCEL, HOLD, RELEASE, UPDATE, or SUBMIT a job, 
transfer to Action Agent - you cannot perform those actions.
"""

ACTION_AGENT_INSTRUCTIONS = f"""{RECOMMENDED_PROMPT_PREFIX}
{NON_OPENAI_SDK_PREFIX}

You are the Slurm Action Agent. You FIX problems and manage jobs.

Read the conversation context to understand what needs to be fixed.
For dangerous actions (cancel, hold, update), warn the user first.
For safe actions (submit), proceed with execution.

## AVAILABLE TOOLS
- scancel: Cancel a job by job_id
- scontrol_hold: Hold a job (prevent from starting)
- scontrol_release: Release a held job
- scontrol_update: Modify job parameters (time limit, partition, etc.)
- sbatch: Submit a new job

## HANDOFF TO ANALYSIS AGENT
If the user needs more information about jobs/cluster before acting,
transfer to Analysis Agent - you focus on ACTIONS, not investigations.
"""

TRIAGE_AGENT_INSTRUCTIONS = f"""{NON_OPENAI_SDK_PREFIX}

You are the Slurm Triage Agent. Route requests to the right specialist.

Transfer to Analysis Agent for read-only queries and investigation.
Transfer to Action Agent for fix requests and job management.
Respond directly for general Slurm questions.
"""


# ============ Multi-Agent System ============
class SlurmMultiAgentSystem:
    """
    Multi-agent Slurm system using SDK handoffs + native MCP tool execution.
    
    Architecture:
    - Triage agent: Routes to specialists
    - Analysis agent: Read-only cluster queries using MCP tools
    - Action agent: Job management using MCP tools
    
    Uses OpenAI Agents SDK's native MCP integration - SDK handles tool
    calls automatically via MCPServerSse.
    """
    
    def __init__(
        self,
        model: str = "gpt-oss:latest",
        base_url: str = "http://localhost:11434/v1",
        mcp_url: str = "http://localhost:3002"
    ):
        self.model_name = model
        self.base_url = base_url
        self.mcp_url = mcp_url
        
        # SDK MCP Server connection
        self._mcp_server: Optional[MCPServerSse] = None
        
        # Conversation history for context
        self.conversation_history: list = []
        
        # Create shared model
        self.sdk_model = create_ollama_model(model)
        
        # Agents will be initialized after MCP connection
        self.analysis_agent = None
        self.action_agent = None
        self.triage_agent = None
        
        self._agents_initialized = False
        
        # Confirmation flow: stores pending dangerous action
        self.pending_confirmation: Optional[PendingConfirmation] = None
    
    def _create_agents(self):
        """
        Create agents that use the shared MCP server.
        
        Tool filtering is handled dynamically by the MCP server's tool_filter,
        which checks context.agent.name to determine which tools to expose.
        """
        # Create agents first without handoffs (will add them after)
        
        # Analysis Agent: SDK will only see ANALYSIS_TOOL_NAMES via the filter
        self.analysis_agent = Agent(
            name="Analysis Agent",
            handoff_description="Handles read-only cluster queries: job status, queue info, resource availability, failure analysis.",
            instructions=ANALYSIS_AGENT_INSTRUCTIONS,
            model=self.sdk_model,
            model_settings=STRICT_JSON_MODEL_SETTINGS,
            mcp_servers=[self._mcp_server],  # SDK handles tools via MCP with filtering
        )
        
        # Action Agent: SDK will only see ACTION_TOOL_NAMES via the filter
        self.action_agent = Agent(
            name="Action Agent", 
            handoff_description="Handles job management: submit, cancel, hold, modify jobs and allocations.",
            instructions=ACTION_AGENT_INSTRUCTIONS,
            model=self.sdk_model,
            model_settings=STRICT_JSON_MODEL_SETTINGS,
            mcp_servers=[self._mcp_server],  # SDK handles tools via MCP with filtering
        )
        
        # Now add cross-handoffs so agents can transfer to each other
        self.analysis_agent.handoffs = [self.action_agent]
        self.action_agent.handoffs = [self.analysis_agent]
        
        # Triage agent: No mcp_servers = no tools, only handoffs
        self.triage_agent = Agent(
            name="Slurm Assistant",
            instructions=TRIAGE_AGENT_INSTRUCTIONS,
            model=self.sdk_model,
            handoffs=[self.analysis_agent, self.action_agent],
            # No mcp_servers - triage only routes, filter would return False anyway
        )
        
        self._agents_initialized = True
        logger.info("Agents created with dynamic tool filtering via MCP and cross-handoffs")
    
    def _describe_dangerous_action(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Generate human-readable description for a dangerous action."""
        job_id = args.get("job_id", "unknown")
        
        if tool_name == "scancel":
            user = args.get("user", "")
            if user:
                return f"Cancel all jobs for user '{user}'"
            return f"Cancel job {job_id}"
        
        elif tool_name == "scontrol_hold":
            return f"Hold job {job_id} (prevent from starting)"
        
        elif tool_name == "scontrol_release":
            return f"Release job {job_id} (allow to run)"
        
        elif tool_name == "scontrol_update":
            updates = []
            if args.get("time_limit"):
                updates.append(f"time={args['time_limit']}")
            if args.get("partition"):
                updates.append(f"partition={args['partition']}")
            if args.get("priority"):
                updates.append(f"priority={args['priority']}")
            if args.get("num_nodes"):
                updates.append(f"nodes={args['num_nodes']}")
            if args.get("num_cpus"):
                updates.append(f"cpus={args['num_cpus']}")
            update_str = ", ".join(updates) if updates else "parameters"
            return f"Update job {job_id}: {update_str}"
        
        return f"Execute {tool_name} with {args}"
    
    async def _ensure_connection(self):
        """Ensure MCP server object is created with tool filtering."""
        if self._mcp_server is None:
            # Create SDK MCP Server connection with dynamic tool filter
            sse_url = f"{self.mcp_url.rstrip('/')}/sse"
            self._mcp_server = MCPServerSse(
                params={
                    "url": sse_url,
                    "timeout": 60,  # HTTP timeout for POST requests
                    "sse_read_timeout": 600,  # SSE read timeout (10 min)
                },
                name="slurm-mcp",
                client_session_timeout_seconds=300,  # MCP session timeout (5 min)
                cache_tools_list=True,  # Cache tools to avoid repeated list_tools calls
                tool_filter=create_agent_tool_filter(),  # Dynamic per-agent filtering!
            )
            logger.info(f"Created MCP server connection to {sse_url} with dynamic tool filter")
    
    async def _ensure_agents(self):
        """Ensure agents are initialized."""
        await self._ensure_connection()
        if not self._agents_initialized:
            self._create_agents()
    
    async def run(self, user_message: str) -> Dict[str, Any]:
        """
        Run multi-agent system with agentic loop.
        
        Flow:
        1. Triage routes to specialist agent
        2. Specialist outputs action → Execute via MCP
        3. SDK executes MCP tools automatically (with per-agent filtering)
        4. Agent continues until done
        
        Returns dict with final answer.
        """
        try:
            logger.info(f"Multi-agent processing: {user_message[:100]}...")
            
            # Ensure agents are initialized with MCP
            await self._ensure_agents()
            
            # MCP server must be connected for agents to access tools
            async with self._mcp_server:
                result = await Runner.run(
                    starting_agent=self.triage_agent,
                    input=user_message
                )
                
                final_agent = result.last_agent.name
                logger.info(f"Agent: {final_agent}")
                output = result.final_output
                
                return {
                    "success": True,
                    "agent": final_agent,
                    "type": "response",
                    "message": str(output),
                    "executed": True
                }
            
        except Exception as e:
            logger.error(f"Multi-agent error: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "type": "error",
                "message": str(e),
                "executed": False
            }
    
    async def run_streaming(
        self,
        user_message: str,
        conversation_history: Optional[list] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Run with streaming using SDK's native streaming support.
        
        SDK handles MCP tool calls automatically with per-agent tool filtering.
        We just stream the events to the UI.
        
        Includes confirmation flow for dangerous actions.
        """
        try:
            # Check if user is responding to a pending confirmation
            user_lower = user_message.strip().lower()
            if self.pending_confirmation:
                if user_lower in ["yes", "y", "confirm", "ok", "sure", "do it"]:
                    # User confirmed - execute the pending action
                    pending = self.pending_confirmation
                    self.pending_confirmation = None
                    
                    yield {"type": "status", "message": f"Executing {pending.tool_name}..."}
                    
                    # Execute the dangerous tool via MCP - need to connect first
                    await self._ensure_agents()
                    async with self._mcp_server:
                        try:
                            result = await self._mcp_server.call_tool(pending.tool_name, pending.arguments)
                            output = str(result) if result else "Action completed"
                            yield {
                                "type": "execution_result",
                                "output": output[:2000] if len(output) > 2000 else output
                            }
                            yield {"type": "final_answer", "message": f"✅ {pending.description} - Done"}
                        except Exception as e:
                            yield {"type": "error", "message": f"Failed to execute: {e}"}
                    
                    yield {"type": "done"}
                    return
                
                elif user_lower in ["no", "n", "cancel", "abort", "nevermind"]:
                    # User cancelled
                    pending = self.pending_confirmation
                    self.pending_confirmation = None
                    yield {"type": "final_answer", "message": f"❌ Cancelled: {pending.description}"}
                    yield {"type": "done"}
                    return
                
                else:
                    # User said something else - remind them about pending confirmation
                    pending = self.pending_confirmation
                    yield {
                        "type": "confirm",
                        "action": pending.tool_name,
                        "parameters": pending.arguments,
                        "message": f"⚠️ You have a pending action: {pending.description}\n\nReply 'yes' to confirm or 'no' to cancel."
                    }
                    yield {"type": "done"}
                    return
            
            yield {"type": "status", "message": "Thinking..."}
            
            # Ensure agents are initialized with MCP
            await self._ensure_agents()
            
            # Build context from conversation history
            context_prompt = user_message
            if conversation_history and len(conversation_history) > 1:
                recent = conversation_history[-7:-1]
                if recent:
                    context_lines = []
                    for msg in recent:
                        role = msg.get("role", "user")
                        content = msg.get("content", "")[:500]
                        if content:
                            context_lines.append(f"{role}: {content}")
                    if context_lines:
                        context_prompt = f"""Previous conversation:
{chr(10).join(context_lines)}

Current request: {user_message}"""
            
            # MCP server must be connected for agents to access tools
            async with self._mcp_server:
                logger.info("MCP connected, starting runner with streaming...")
                
                # Use SDK streaming - it handles tool calls automatically
                result = Runner.run_streamed(
                    starting_agent=self.triage_agent,
                    input=context_prompt
                )
                
                logger.info("Runner started, iterating events...")
                
                final_message_yielded = False
                
                async for event in result.stream_events():
                    event_type = type(event).__name__
                    
                    if event_type == "RawResponsesStreamEvent":
                        # Raw model output - extract content from OpenAI streaming format
                        data = event.data
                        content = None
                        
                        # OpenAI chat completions streaming format: data.choices[0].delta.content
                        if hasattr(data, 'choices') and data.choices:
                            choice = data.choices[0]
                            if hasattr(choice, 'delta') and choice.delta:
                                content = getattr(choice.delta, 'content', None)
                            # Non-streaming format: choice.message.content
                            elif hasattr(choice, 'message') and choice.message:
                                content = getattr(choice.message, 'content', None)
                        
                        # Fallback: try direct attributes
                        if not content and hasattr(data, 'delta'):
                            delta = data.delta
                            if delta:
                                content = getattr(delta, 'content', None)
                        
                        if not content:
                            content = getattr(data, 'content', None)
                        
                        if content:
                            # Stream the thinking/reasoning content
                            logger.debug(f"Raw content: {content[:100]}...")
                            yield {"type": "thinking", "thought": content}
                    
                    elif event_type == "RunItemStreamEvent":
                        item = event.item
                        item_type = type(item).__name__
                        logger.info(f"RunItem: {item_type}")
                        
                        if item_type == "ToolCallItem":
                            # Agent calling a tool - try multiple attribute names
                            tool_name = (
                                getattr(item, 'name', None) or
                                getattr(item, 'tool_name', None) or
                                getattr(getattr(item, 'raw_item', None), 'name', None) or
                                'unknown'
                            )
                            # Try to get arguments from various places
                            tool_args = (
                                getattr(item, 'arguments', None) or
                                getattr(item, 'call_arguments', None) or
                                getattr(getattr(item, 'raw_item', None), 'arguments', None) or
                                '{}'
                            )
                            logger.info(f"Tool call: {tool_name}")
                            try:
                                args_dict = json.loads(tool_args) if isinstance(tool_args, str) else (tool_args or {})
                            except:
                                args_dict = {}
                            
                            # Check if this is a dangerous tool requiring confirmation
                            if tool_name in DANGEROUS_TOOLS:
                                description = self._describe_dangerous_action(tool_name, args_dict)
                                self.pending_confirmation = PendingConfirmation(
                                    tool_name=tool_name,
                                    arguments=args_dict,
                                    description=description
                                )
                                logger.info(f"Dangerous action detected: {description}")
                                yield {
                                    "type": "confirm",
                                    "action": tool_name,
                                    "parameters": args_dict,
                                    "message": f"⚠️ **Confirmation Required**\n\n{description}\n\nThis action cannot be undone. Reply 'yes' to confirm or 'no' to cancel."
                                }
                                yield {"type": "done"}
                                return  # Stop processing - wait for user confirmation
                            
                            yield {
                                "type": "acting",
                                "action": tool_name,
                                "parameters": args_dict
                            }
                        
                        elif item_type == "ToolCallOutputItem":
                            # Tool returned result
                            output = getattr(item, 'output', '')
                            logger.info(f"Tool output received: {len(str(output))} chars")
                            yield {
                                "type": "execution_result",
                                "output": output[:2000] if len(str(output)) > 2000 else output
                            }
                        
                        elif item_type == "MessageOutputItem":
                            # Final message from agent
                            content = ""
                            if hasattr(item, 'content'):
                                for part in item.content:
                                    if hasattr(part, 'text'):
                                        content += part.text
                            if content:
                                logger.info(f"Final message: {content[:100]}...")
                                final_message_yielded = True
                                yield {"type": "final_answer", "message": content}
                        
                        elif item_type == "HandoffOutputItem":
                            # Agent handoff
                            target = getattr(item, 'target_agent', None)
                            if target:
                                logger.info(f"Handoff to: {target.name}")
                                yield {"type": "routed", "agent": target.name}
                    
                    elif event_type == "AgentUpdatedStreamEvent":
                        # Agent changed (via handoff)
                        new_agent = getattr(event, 'agent', None)
                        if new_agent:
                            logger.info(f"Agent updated: {new_agent.name}")
                            yield {"type": "status", "message": f"Transferred to {new_agent.name}"}
                
                # Get final output only if no message was yielded during streaming
                if not final_message_yielded:
                    logger.info("Stream ended, getting final output...")
                    final_result = result.final_output
                    if final_result:
                        logger.info(f"Final result: {str(final_result)[:200]}")
                        yield {"type": "final_answer", "message": str(final_result)}
                
                yield {"type": "done"}
                
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            import traceback
            traceback.print_exc()
            yield {"type": "error", "message": str(e)}
    
    async def disconnect(self):
        """Clean up connections."""
        # SDK MCP server cleanup is handled by context manager
        self._mcp_server = None
        self._agents_initialized = False
    
    async def __aenter__(self):
        await self._ensure_connection()
        return self
    
    async def __aexit__(self, *args):
        await self.disconnect()


# ============ Convenience Functions ============

async def run_multi_agent(message: str, mcp_url: str = "http://localhost:3002") -> Dict[str, Any]:
    """Quick one-shot multi-agent execution."""
    system = SlurmMultiAgentSystem(mcp_url=mcp_url)
    try:
        return await system.run(message)
    finally:
        await system.disconnect()


async def run_multi_agent_streaming(message: str, conversation_history: Optional[list] = None, mcp_url: str = "http://localhost:3002") -> AsyncGenerator[Dict[str, Any], None]:
    """Quick one-shot streaming execution."""
    system = SlurmMultiAgentSystem(mcp_url=mcp_url)
    try:
        async for event in system.run_streaming(message, conversation_history):
            yield event
    finally:
        await system.disconnect()
