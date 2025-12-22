"""
Slurm ReAct Agent with Sub-Agents as Tools

Architecture:
- Main ReAct Agent: Keeps context, orchestrates everything
- Analysis Sub-Agent: Called as a tool for read-only queries  
- Action Sub-Agent: Called as a tool for job management
- SQLiteSession: Automatic conversation history management
- SlurmContext: Custom RunContext for confirmation state

Sub-agents return results to main agent, maintaining context coherence.
"""
import logging
import re
import json
from typing import Optional, AsyncGenerator, Dict, Any, Set, List
from dataclasses import dataclass, field

from agents import Agent, Runner, SQLiteSession, RunContextWrapper, ItemHelpers
from agents.agent import ToolsToFinalOutputResult
from agents.result import RunResult, RunResultStreaming
from agents.mcp import MCPServerSse, ToolFilterContext
from agents.mcp.util import MCPUtil
from agents.tool import FunctionTool, FunctionToolResult
from agents.tool_context import ToolContext
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from agents.model_settings import ModelSettings
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


# ============ Custom Output Extractors ============
async def extract_subagent_output(result: RunResult | RunResultStreaming) -> str:
    """
    Extract structured output from sub-agent runs.
    
    This ensures sub-agents return data, not conversational responses.
    If the sub-agent used tools, we format the tool results.
    Otherwise, we return the final output with a prefix indicating it's internal.
    """
    # Get the final output
    if isinstance(result, RunResultStreaming):
        final_output = await result.final_output_async()
    else:
        final_output = result.final_output
    
    # Check if tools were called - if so, include tool outputs
    tool_outputs = []
    if hasattr(result, 'new_items'):
        for item in result.new_items:
            item_type = type(item).__name__
            if item_type == "ToolCallOutputItem":
                tool_name = getattr(item, 'name', '') or getattr(item, 'tool_name', '')
                output = getattr(item, 'output', '')
                if output:
                    tool_outputs.append(f"[{tool_name}]: {output}")
    
    # Build structured response
    if tool_outputs:
        tools_section = "\n".join(tool_outputs)
        return f"TOOL_RESULTS:\n{tools_section}\n\nSUMMARY: {final_output}"
    else:
        # No tools called - just return the output but mark it as internal
        return f"INTERNAL_RESPONSE: {final_output}"


# ============ Chart-Filtering Session Wrapper ============

class ChartFilteredSession:
    """
    Wraps SQLiteSession to filter chart artifacts from conversation history.
    
    The agent never sees chart HTML in history - the framework handles chart display.
    This ensures the LLM isn't confused by HTML artifacts in previous messages.
    """
    
    def __init__(self, session: SQLiteSession):
        self._session = session
    
    @staticmethod
    def _strip_charts(text: str) -> str:
        """Remove chart artifacts (mermaid blocks) from text."""
        if not text:
            return text
        # Remove mermaid code blocks from history to keep context clean
        pattern = r'```mermaid\n.*?```'
        return re.sub(pattern, '', text, flags=re.DOTALL).strip()
    
    @staticmethod
    def _filter_history_item(item):
        """Filter chart artifacts from a single history item."""
        # Handle different item types from the SDK
        if hasattr(item, 'content'):
            # Message-like item
            if isinstance(item.content, str):
                filtered_content = ChartFilteredSession._strip_charts(item.content)
                # Create a copy with filtered content
                if hasattr(item, '_replace'):  # namedtuple
                    return item._replace(content=filtered_content)
                elif hasattr(item, '__dict__'):
                    # Object - create modified copy
                    import copy
                    new_item = copy.copy(item)
                    new_item.content = filtered_content
                    return new_item
        return item
    
    async def get_session_history(self):
        """Get history with chart artifacts filtered out."""
        history = await self._session.get_session_history()
        if not history:
            return history
        
        # Filter each item in history
        filtered = []
        for item in history:
            filtered_item = self._filter_history_item(item)
            filtered.append(filtered_item)
        
        return filtered
    
    async def add_items(self, items):
        """Add items to history (charts included for persistence, filtered on read)."""
        return await self._session.add_items(items)
    
    async def clear_session(self):
        """Clear session history."""
        return await self._session.clear_session()
    
    def __getattr__(self, name):
        """Delegate unknown attributes to wrapped session."""
        return getattr(self._session, name)


# ============ Pending Actions Store ============
import sqlite3
import threading

class PendingActionsStore:
    """
    Persistent store for pending actions that require confirmation.
    Uses SQLite for persistence across runs.
    """
    _lock = threading.Lock()
    
    def __init__(self, db_path: str = "/tmp/slurm_pending_actions.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_actions (
                    session_id TEXT PRIMARY KEY,
                    actions TEXT,
                    created_at REAL
                )
            """)
            conn.commit()
            conn.close()
    
    def store_pending(self, session_id: str, actions: List[Dict[str, Any]]):
        """Store pending actions for a session."""
        import time
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT OR REPLACE INTO pending_actions (session_id, actions, created_at) VALUES (?, ?, ?)",
                (session_id, json.dumps(actions), time.time())
            )
            conn.commit()
            conn.close()
            logger.info(f"Stored {len(actions)} pending actions for session {session_id}")
    
    def get_pending(self, session_id: str) -> List[Dict[str, Any]]:
        """Get pending actions for a session."""
        import time
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute(
                "SELECT actions, created_at FROM pending_actions WHERE session_id = ?",
                (session_id,)
            )
            row = cursor.fetchone()
            conn.close()
            
            if row:
                actions_json, created_at = row
                # Only return if less than 1 hour old
                if time.time() - created_at < 3600:
                    return json.loads(actions_json)
            return []
    
    def clear_pending(self, session_id: str):
        """Clear pending actions for a session."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("DELETE FROM pending_actions WHERE session_id = ?", (session_id,))
            conn.commit()
            conn.close()
            logger.info(f"Cleared pending actions for session {session_id}")


# Global pending actions store
_pending_store = PendingActionsStore()


# ============ Run Context ============
@dataclass
class SlurmContext:
    """
    Custom context passed through the agent run.
    Accessible via RunContextWrapper.context in tools and guardrails.
    
    Note: pending_actions are now stored persistently via PendingActionsStore,
    allowing them to survive across runs for confirmation flow.
    
    Chart artifacts are stored here during the run and appended to response at stream end.
    """
    session_id: str = "default"
    chart_artifacts: List[str] = field(default_factory=list)
    
    def add_chart_artifact(self, mermaid_code: str):
        """Store a chart artifact for later appending to response."""
        self.chart_artifacts.append(mermaid_code)
        logger.debug(f"Stored chart artifact ({len(mermaid_code)} chars), total: {len(self.chart_artifacts)}")
    
    def get_pending_actions(self) -> List[Dict[str, Any]]:
        """Get pending actions from persistent store."""
        return _pending_store.get_pending(self.session_id)
    
    def add_pending_action(self, tool_name: str, args: Dict[str, Any], description: str):
        """Add a pending action to persistent store."""
        actions = self.get_pending_actions()
        actions.append({
            "tool": tool_name,
            "args": args,
            "description": description
        })
        _pending_store.store_pending(self.session_id, actions)
        logger.info(f"Added pending action {tool_name} - {description}")
    
    def clear_pending(self):
        """Clear pending actions from persistent store."""
        _pending_store.clear_pending(self.session_id)


# ============ Tool Sets ============
# Analysis tools: Read-only data gathering + web search for debugging
ANALYSIS_TOOL_NAMES: Set[str] = {"run_analysis","squeue", "sacct", "sinfo", "scontrol_show" , "web_search"}

# Visualization tools: For main agent direct access
VISUALIZATION_TOOLS: Set[str] = {"generate_chart"}

# Safe action tools (no confirmation needed - read-only or low-risk)
SAFE_ACTION_TOOLS: Set[str] = {
    "squeue", "sacct", "sinfo", "scontrol_show",  # Read-only queries
    "srun", "salloc",  # Interactive execution (user's own resources)
    "sacctmgr_show", "sreport",  # Read-only accounting queries
    "web_search"  # Web search for debugging/docs
}

# Dangerous tools (modify cluster state - need confirmation via context)
DANGEROUS_TOOLS: Set[str] = {
    # Job control
    "scancel", "scontrol_hold", "scontrol_release", "scontrol_update", "sbatch",
    "scontrol_requeue",
    # Admin operations (high risk)
    "scontrol_create", "scontrol_delete", "scontrol_reconfigure",
    # Accounting modifications (high risk)
    "sacctmgr_add", "sacctmgr_modify", "sacctmgr_delete"
}

# All action tools (including dangerous ones)
ACTION_TOOL_NAMES: Set[str] = SAFE_ACTION_TOOLS | DANGEROUS_TOOLS


# ============ Dynamic Tool Filter ============
def create_tool_filter_for_agent(allowed_tools: Set[str]):
    """Create a tool filter that only allows specific tools."""
    async def tool_filter(context: ToolFilterContext, tool) -> bool:
        allowed = tool.name in allowed_tools
        logger.debug(f"Tool filter: {tool.name} -> {'ALLOWED' if allowed else 'BLOCKED'}")
        return allowed
    return tool_filter


def create_static_tool_filter(allowed_tools: Set[str]) -> dict:
    """Create a static tool filter (doesn't require run_context)."""
    return {"allowed_tool_names": list(allowed_tools)}


# ============ Model Configuration ============
def create_ollama_model(model_name: str = "gpt-oss:latest", base_url: str = "http://localhost:11434/v1") -> OpenAIChatCompletionsModel:
    """Create Ollama-compatible model."""
    client = AsyncOpenAI(base_url=base_url, api_key="ollama")
    return OpenAIChatCompletionsModel(model=model_name, openai_client=client)


# Model settings for reasoning (main agent) - qwen3-coder thinks before answering
REASONING_MODEL_SETTINGS = ModelSettings(
    temperature=0.0,  # Deterministic for reproducible evaluation
)

# Model settings for tool execution (sub-agents) - gpt-oss executes precisely  
TOOL_MODEL_SETTINGS = ModelSettings(
    temperature=0.0,  # Deterministic tool execution
    tool_choice="required",  # Force tool usage - sub-agents MUST call tools
)

# Legacy alias
MODEL_SETTINGS = TOOL_MODEL_SETTINGS


# ============ Agent Instructions ============

MAIN_AGENT_INSTRUCTIONS = """You are a Slurm HPC cluster assistant.

## CRITICAL RULES
1. ALWAYS call tools first - NEVER say "I can't" or make up data
2. You CAN search the web - use analyze_cluster("search for: <query>")
3. Use analyze_cluster for ALL data gathering including web searches
4. Use manage_jobs for actions
5. DANGEROUS ACTIONS: If manage_jobs returns "QUEUED", tell user to confirm with confirm_action()

## TOOLS
- **analyze_cluster(request)** - Gather cluster data OR search the web. Examples:
  - analyze_cluster("get cluster status")
  - analyze_cluster("search for: CUDA illegal memory access solution")
  - analyze_cluster("search for: MPI segfault fix")
- **generate_chart(chart_id)** - Create visualizations
- **manage_jobs(request)** - Execute job actions (cancel, hold, submit, etc.)
- **confirm_action()** / **cancel_action()** - Handle pending dangerous actions

## HANDLING DANGEROUS OPERATIONS
When manage_jobs returns "QUEUED: ...", you MUST:
1. Tell the user what action is pending
2. Ask them to confirm by saying "confirm" or "yes"
3. Do NOT say the action was completed - it's still pending!

## OUTPUT FORMAT FOR ANALYSIS
When presenting cluster status, use this structured format:

### Cluster Snapshot (timestamp)
| Partition | Total nodes | Running/Ready | Down/Drain | Notes |
|-----------|-------------|---------------|------------|-------|

### Job Landscape
| Job ID | User | Partition | Nodes | Status | Exit | Primary error |
|--------|------|-----------|-------|--------|------|---------------|

### Immediate Recommendations
| # | Action | Reason |
|---|--------|--------|

## WORKFLOW
1. When user asks to search: call analyze_cluster("search for: <query>")
2. For cluster data: call analyze_cluster with description
3. Present findings with specific details
4. For visualizations, call generate_chart
5. For actions, call manage_jobs and handle QUEUED responses

"""

ANALYSIS_SUBAGENT_INSTRUCTIONS = """You gather data by calling ONE tool, then return.

## TOOLS
- **web_search(query, search_type, fetch_content)** - Search the internet for documentation, tutorials, error solutions
- **run_analysis(script_id)** - Get current cluster status, job info, node info
- **scontrol_show** - Get specific job/node details
- **squeue/sacct/sinfo** - Raw Slurm queries

## WHEN TO USE WEB_SEARCH
Use web_search when the user wants to:
- Find documentation or tutorials
- Look up error messages or solutions
- Learn how to do something (how to, example, guide)
- Find best practices or recommendations
- Search for external information not in the cluster

### web_search parameters:
- query: The search query
- search_type: "error" for debugging, "docs" for documentation, "slurm" for Slurm-specific
- fetch_content: Set to TRUE for detailed answers (reads full web pages), FALSE for quick search

Use fetch_content=true when:
- User needs detailed step-by-step instructions
- Debugging complex errors
- Looking for code examples or configuration

Use fetch_content=false (default) when:
- Quick lookup of what something means
- Finding relevant URLs
- Simple questions

## WHEN TO USE RUN_ANALYSIS
Use run_analysis when the user wants to:
- Check current cluster status
- See running/pending/failed jobs
- Get node information
- Analyze resource usage

## RULES
1. Call ONE tool only, then stop
2. Return raw tool output - do not summarize

"""

ACTION_SUBAGENT_INSTRUCTIONS = """You execute cluster actions by calling tools. You MUST call a tool for EVERY action request.

## CRITICAL RULES
1. NEVER say an action was done without calling the tool first
2. ALWAYS call the appropriate tool - do not make up results
3. If a tool returns "QUEUED", report that it needs user confirmation
4. If you cannot find the right tool, say so - do not fabricate success

## TOOLS
- **Job control**: sbatch, scancel, scontrol_hold, scontrol_release, scontrol_update, scontrol_requeue
- **Interactive**: srun, salloc  
- **Admin**: scontrol_create, scontrol_delete, scontrol_reconfigure
- **Accounting**: sacctmgr_show, sacctmgr_add, sacctmgr_modify, sacctmgr_delete, sreport

## WORKFLOW
1. Identify the correct tool for the action
2. Call the tool with the required parameters
3. Return the EXACT tool response - do not modify or summarize
4. If tool says "QUEUED", user must confirm before execution
"""


# ============ Main System ============
class SlurmMultiAgentSystem:
    """
    Main ReAct agent with sub-agents as tools.
    
    Architecture:
    - Main agent: Orchestrates, keeps context, calls sub-agents
    - Analysis sub-agent: Read-only investigations (as tool)
    - Action sub-agent: Job management (as tool)
    """
    
    def __init__(
        self,
        reasoning_model: str = "qwen3-coder:latest",  # Main agent - thinks/reasons
        tool_model: str = "gpt-oss:20b",  # Sub-agents - executes tools
        base_url: str = "http://localhost:11434/v1",
        mcp_url: str = "http://localhost:3002",
        session_id: str = "default"
    ):
        self.reasoning_model_name = reasoning_model
        self.tool_model_name = tool_model
        self.base_url = base_url
        self.mcp_url = mcp_url
        self.session_id = session_id
        
        # Session for conversation history (wrapped to filter chart artifacts)
        self._session: Optional[ChartFilteredSession] = None
        
        # MCP servers (chart tool uses direct HTTP, not MCP SDK)
        self._analysis_mcp: Optional[MCPServerSse] = None
        self._action_mcp: Optional[MCPServerSse] = None
        self._dangerous_mcp: Optional[MCPServerSse] = None  # For guarded dangerous tools
        
        # Models - separate for reasoning vs tool execution
        self.reasoning_sdk_model = create_ollama_model(reasoning_model, base_url)  # qwen3-coder
        self.tool_sdk_model = create_ollama_model(tool_model, base_url)  # gpt-oss
        
        # Agents
        self.main_agent = None
        self.analysis_subagent = None
        self.action_subagent = None
        
        self._agents_initialized = False
    
    def _get_session(self) -> ChartFilteredSession:
        """Get or create session for conversation history with chart filtering."""
        if self._session is None:
            # Use persistent SQLite file for conversation history
            sqlite_session = SQLiteSession(
                self.session_id, 
                "/tmp/slurm_agent_conversations.db"
            )
            # Wrap with chart filter so agent never sees HTML artifacts in history
            self._session = ChartFilteredSession(sqlite_session)
            logger.info(f"Created ChartFilteredSession for session_id: {self.session_id}")
        return self._session
    
    def _create_mcp_server(self, tool_filter_func=None) -> MCPServerSse:
        """Create MCP server with optional tool filter."""
        sse_url = f"{self.mcp_url.rstrip('/')}/sse"
        return MCPServerSse(
            params={
                "url": sse_url,
                "timeout": 60,
                "sse_read_timeout": 600,
            },
            name="slurm-mcp",
            client_session_timeout_seconds=300,
            cache_tools_list=True,
            tool_filter=tool_filter_func,
        )
    
    async def _ensure_agents(self):
        """Initialize MCP servers and agents with tool guardrails on dangerous MCP tools."""
        if self._agents_initialized:
            logger.info("Agents already initialized, skipping")
            return
        
        logger.info("Initializing agents for the first time...")
        
        # Create MCP servers with tool filters
        # Analysis: read-only tools
        self._analysis_mcp = self._create_mcp_server(
            create_tool_filter_for_agent(ANALYSIS_TOOL_NAMES)
        )
        # Action: Only SAFE tools via MCP (dangerous tools will be added as guarded FunctionTools)
        self._action_mcp = self._create_mcp_server(
            create_tool_filter_for_agent(SAFE_ACTION_TOOLS)
        )
        # Note: _viz_mcp no longer needed - chart wrapper uses direct HTTP to MCP
        
        logger.info("Created MCP servers for sub-agents")
        
        # Tool handler to mark web_search results for stream detection
        def analysis_tool_handler(
            context: RunContextWrapper[Any],
            tool_results: List[FunctionToolResult]
        ) -> ToolsToFinalOutputResult:
            """Process tool results - mark web_search with [WEB_SEARCH]: prefix."""
            logger.info(f"[tool_use_behavior] Called with {len(tool_results)} results")
            
            for i, result in enumerate(tool_results):
                # Debug: log all attributes
                result_attrs = [a for a in dir(result) if not a.startswith('_')]
                logger.info(f"[tool_use_behavior] Result {i} attrs: {result_attrs}")
                
                # Try multiple ways to get tool name (FunctionTool vs MCP tool)
                tool_name = ""
                if hasattr(result, 'tool'):
                    tool_obj = result.tool
                    tool_name = getattr(tool_obj, 'name', str(tool_obj))
                    logger.info(f"[tool_use_behavior] Tool from result.tool: {tool_name}")
                if not tool_name and hasattr(result, 'name'):
                    tool_name = result.name
                    logger.info(f"[tool_use_behavior] Tool from result.name: {tool_name}")
                
                output_str = str(result.output) if hasattr(result, 'output') and result.output else ""
                logger.info(f"[tool_use_behavior] Tool: '{tool_name}', output len: {len(output_str)}, preview: {output_str[:200]}")
                
                # Check for web_search by name OR by output content
                is_web_search = (
                    "web_search" in tool_name.lower() or 
                    "[WEB_SEARCH]:" in output_str or
                    ("URL:" in output_str and "http" in output_str)
                )
                
                logger.info(f"[tool_use_behavior] is_web_search={is_web_search}")
                
                if is_web_search and output_str:
                    # Mark the output so streaming can detect it
                    if not output_str.startswith("[WEB_SEARCH]:"):
                        marked_output = f"[WEB_SEARCH]:\n{output_str}"
                    else:
                        marked_output = output_str
                    logger.info(f"[tool_use_behavior] RETURNING web search output ({len(marked_output)} chars)")
                    return ToolsToFinalOutputResult(
                        is_final_output=True,
                        final_output=marked_output
                    )
            
            logger.info("[tool_use_behavior] No web search detected, letting LLM continue")
            # Let LLM continue processing for other tools
            return ToolsToFinalOutputResult(is_final_output=False, final_output=None)
        
        # Create sub-agents with TOOL model (gpt-oss) - precise execution
        self.analysis_subagent = Agent(
            name="Analysis Sub-Agent",
            instructions=ANALYSIS_SUBAGENT_INSTRUCTIONS,
            model=self.tool_sdk_model,  # gpt-oss for tool execution
            model_settings=TOOL_MODEL_SETTINGS,
            mcp_servers=[self._analysis_mcp],
            tool_use_behavior=analysis_tool_handler,  # Mark web_search results
        )
        
        # For action sub-agent: we need to add guarded dangerous tools
        # Use STATIC filter (doesn't require run_context for list_tools)
        self._dangerous_mcp = self._create_mcp_server(
            create_static_tool_filter(DANGEROUS_TOOLS)
        )
        
        # Create guarded FunctionTools for each dangerous action
        dangerous_function_tools = await self._create_guarded_dangerous_tools()
        
        # Action sub-agent with safe MCP tools + guarded dangerous tools
        self.action_subagent = Agent(
            name="Action Sub-Agent",
            instructions=ACTION_SUBAGENT_INSTRUCTIONS,
            model=self.tool_sdk_model,  # gpt-oss for tool execution
            model_settings=TOOL_MODEL_SETTINGS,
            mcp_servers=[self._action_mcp],
            tools=dangerous_function_tools,  # Add guarded dangerous tools
        )
        
        # Convert sub-agents to tools for main agent
        # Use custom_output_extractor to get structured data instead of conversational messages
        analyze_tool = self.analysis_subagent.as_tool(
            tool_name="analyze_cluster",
            tool_description="Gather raw cluster data: job status, queue info, node status. Pass a description of what data is needed. Returns structured data, not user-facing messages.",
            custom_output_extractor=extract_subagent_output,
        )
        
        action_tool = self.action_subagent.as_tool(
            tool_name="manage_jobs",
            tool_description="Execute job actions: cancel, hold, release, update, submit. Pass a description of the action. Returns execution results or lists missing required info.",
            custom_output_extractor=extract_subagent_output,
        )
        
        # Create confirm_action tool - allows agent to execute pending actions after user confirms
        async def confirm_action_fn(ctx: ToolContext[SlurmContext], args: str) -> str:
            """
            Execute all pending dangerous actions after user confirms.
            Call this tool when the user has confirmed they want to proceed with a pending action.
            """
            pending_actions = ctx.context.get_pending_actions()
            
            if not pending_actions:
                return "No pending actions to confirm. The action may have already been executed or cancelled."
            
            results = []
            
            # Get tools list once (MCP server is already open from outer context)
            try:
                mcp_tools = await self._dangerous_mcp.list_tools()
            except Exception as e:
                logger.error(f"Failed to get MCP tools: {e}")
                ctx.context.clear_pending()
                return f"Error: Failed to connect to MCP server - {e}"
            
            for pending in pending_actions:
                tool_name = pending["tool"]
                tool_args = pending["args"]
                description = pending["description"]
                
                try:
                    # Find the MCP tool
                    target_tool = None
                    for t in mcp_tools:
                        if t.name == tool_name:
                            target_tool = t
                            break
                    
                    if target_tool:
                        result = await MCPUtil.invoke_mcp_tool(
                            server=self._dangerous_mcp,
                            tool=target_tool,
                            context=ctx,
                            input_json=json.dumps(tool_args)
                        )
                        results.append(f"✅ {description}: {result}")
                    else:
                        results.append(f"❌ Tool {tool_name} not found")
                except Exception as e:
                    logger.error(f"Error executing confirmed action {tool_name}: {e}")
                    results.append(f"❌ {description}: Error - {e}")
            
            ctx.context.clear_pending()
            return "\n".join(results) if results else "No actions executed"
        
        confirm_tool = FunctionTool(
            name="confirm_action",
            description="Execute ALL queued dangerous actions after user confirms. Call when user says yes/ok/confirm/proceed.",
            params_json_schema={"type": "object", "properties": {}, "required": []},
            on_invoke_tool=confirm_action_fn,
        )
        
        # Create cancel_action tool - allows agent to cancel pending actions when user declines
        async def cancel_action_fn(ctx: ToolContext[SlurmContext], args: str) -> str:
            """
            Cancel all pending dangerous actions.
            Call this tool when the user has declined/cancelled a pending action.
            """
            pending_actions = ctx.context.get_pending_actions()
            
            if not pending_actions:
                return "No pending actions to cancel."
            
            descriptions = [p["description"] for p in pending_actions]
            ctx.context.clear_pending()
            return f"❌ Cancelled {len(descriptions)} action(s): {', '.join(descriptions)}"
        
        cancel_tool = FunctionTool(
            name="cancel_action",
            description="Cancel ALL queued dangerous actions. Call when user says no/cancel/stop/nevermind.",
            params_json_schema={"type": "object", "properties": {}, "required": []},
            on_invoke_tool=cancel_action_fn,
        )
        
        # Create check_pending tool - allows agent to see what actions are waiting for confirmation
        async def check_pending_fn(ctx: ToolContext[SlurmContext], args: str) -> str:
            """
            Check what actions are pending confirmation.
            """
            pending = ctx.context.get_pending_actions()
            if not pending:
                return "No pending actions."
            
            descriptions = [f"- {p['description']}" for p in pending]
            return f"Pending actions awaiting confirmation:\n" + "\n".join(descriptions)
        
        check_pending_tool = FunctionTool(
            name="check_pending_actions",
            description="Check what dangerous actions are pending user confirmation.",
            params_json_schema={"type": "object", "properties": {}, "required": []},
            on_invoke_tool=check_pending_fn,
        )
        
        # Create wrapper for generate_chart that hides artifact from LLM
        # This calls MCP via HTTP directly (stateless mode), stores artifact in context, returns only summary
        # Using FunctionTool with ToolContext (not @function_tool - doesn't work inside methods)
        
        # Valid chart IDs - new conceptual charts + legacy charts
        VALID_CHARTS = {
            # New utility-focused charts
            "cluster_topology",   # Hierarchical view: cluster → partitions → nodes
            "job_lifecycle",      # Gantt timeline: job progression over time
            "resource_map",       # Who's using what: user → resources allocation
            "pending_analysis",   # Why waiting: pending jobs with reasons
            "system_health",      # Dashboard: health indicators and alerts
            # Legacy charts (still supported)
            "job_distribution", "node_status", "resource_usage", "queue_timeline", "live_dashboard"
        }
        
        # Need to capture self.mcp_url for use in the function
        mcp_base_url = self.mcp_url.rstrip('/')
        
        async def generate_chart_wrapper(ctx: ToolContext[SlurmContext], args_json: str) -> str:
            """
            Generate a chart visualization. The chart will be displayed to the user automatically.
            """
            import httpx
            import uuid
            
            # Parse chart_id from JSON args
            chart_id = "system_health"
            try:
                if args_json:
                    parsed = json.loads(args_json)
                    if isinstance(parsed, dict):
                        chart_id = parsed.get("chart_id", "system_health")
                    elif isinstance(parsed, str):
                        chart_id = parsed
            except json.JSONDecodeError:
                # Try to extract chart_id from malformed input
                pass
            
            # Normalize and validate chart_id
            chart_id_clean = (chart_id or "system_health").strip().lower().replace(" ", "_").replace("-", "_")
            
            # Map common variations to valid chart IDs
            if chart_id_clean not in VALID_CHARTS:
                # New charts - priority mappings
                if "health" in chart_id_clean or "status" in chart_id_clean or "overview" in chart_id_clean:
                    chart_id_clean = "system_health"
                elif "topology" in chart_id_clean or "structure" in chart_id_clean or "cluster" in chart_id_clean:
                    chart_id_clean = "cluster_topology"
                elif "pending" in chart_id_clean or "waiting" in chart_id_clean or "queue" in chart_id_clean or "why" in chart_id_clean:
                    chart_id_clean = "pending_analysis"
                elif "allocation" in chart_id_clean or "who" in chart_id_clean or "user" in chart_id_clean:
                    chart_id_clean = "resource_map"
                elif "lifecycle" in chart_id_clean or "timeline" in chart_id_clean or "gantt" in chart_id_clean:
                    chart_id_clean = "job_lifecycle"
                # Legacy mappings
                elif "dashboard" in chart_id_clean or "live" in chart_id_clean:
                    chart_id_clean = "live_dashboard"
                elif "distribution" in chart_id_clean or "pie" in chart_id_clean:
                    chart_id_clean = "job_distribution"
                elif "node" in chart_id_clean:
                    chart_id_clean = "node_status"
                elif "resource" in chart_id_clean or "usage" in chart_id_clean or "cpu" in chart_id_clean:
                    chart_id_clean = "resource_usage"
                elif "job" in chart_id_clean:
                    chart_id_clean = "job_lifecycle"
                else:
                    chart_id_clean = "system_health"
                    logger.warning(f"Unknown chart_id '{chart_id}', defaulting to system_health")
            
            logger.info(f"generate_chart: chart_id='{chart_id_clean}' (original: '{chart_id}')")
            
            try:
                # Call MCP server directly via HTTP in STATELESS mode (no session_id)
                message_url = f"{mcp_base_url}/message"
                
                jsonrpc_request = {
                    "jsonrpc": "2.0",
                    "id": str(uuid.uuid4()),
                    "method": "tools/call",
                    "params": {
                        "name": "generate_chart",
                        "arguments": {"chart_id": chart_id_clean}
                    }
                }
                
                async with httpx.AsyncClient(timeout=60) as client:
                    response = await client.post(message_url, json=jsonrpc_request)
                    
                    if response.status_code != 200:
                        logger.warning(f"MCP returned {response.status_code}: {response.text}")
                        return f"❌ MCP error: {response.status_code}"
                    
                    result_data = response.json().get("result", {})
                
                # Parse the response to extract artifact
                summary = f"✅ Chart '{chart_id_clean}' generated"
                artifact = None
                
                content_items = result_data.get("content", [])
                for item in content_items:
                    if item.get("type") == "resource":
                        # Check for resource with mermaid mimetype
                        resource = item.get("resource", {})
                        if resource.get("mimeType") == "text/x-mermaid":
                            artifact = resource.get("text")
                    elif item.get("type") == "text":
                        # Check if text content is mermaid code
                        text = item.get("text", "")
                        # Detect mermaid chart types (case-insensitive check for common patterns)
                        mermaid_markers = [
                            "xychart-beta", "xychart", 
                            "pie", "pie showData",
                            "gantt", 
                            "flowchart", "flowchart TB", "flowchart LR",
                            "graph ", "graph TB", "graph LR",
                            "%%{init:",  # Mermaid config directive
                            "---\nconfig",  # YAML frontmatter for mermaid
                        ]
                        text_lower = text.lower()
                        is_mermaid = any(marker.lower() in text_lower for marker in mermaid_markers)
                        # Also check if starts with --- (YAML frontmatter)
                        if text.strip().startswith("---"):
                            is_mermaid = True
                        
                        if is_mermaid:
                            artifact = text
                        else:
                            summary = text
                
                # Store artifact in context if found
                if artifact:
                    ctx.context.add_chart_artifact(artifact)
                    logger.info(f"Chart artifact stored in context ({len(artifact)} chars)")
                    logger.info(f"Context id: {id(ctx.context)}, artifacts count: {len(ctx.context.chart_artifacts)}")
                else:
                    logger.warning("No mermaid artifact found in MCP response")
                    logger.warning(f"Content items received: {content_items}")
                
                # Return only summary to LLM - artifact is hidden!
                return summary
                    
            except Exception as e:
                logger.error(f"generate_chart error: {e}")
                import traceback
                traceback.print_exc()
                return f"❌ Chart generation failed: {str(e)}"
        
        # Create FunctionTool for generate_chart
        chart_tool = FunctionTool(
            name="generate_chart",
            description="""Generate a visualization chart.

Charts for operations:
- system_health: Dashboard with health indicators and alerts (DEFAULT)
- cluster_topology: Cluster structure (partitions → nodes → states)  
- pending_analysis: Why jobs are waiting (bottleneck diagnosis)
- resource_map: Who's using what resources
- job_lifecycle: Gantt timeline of job progression

Legacy: job_distribution, node_status, resource_usage, queue_timeline, live_dashboard""",
            params_json_schema={
                "type": "object",
                "properties": {
                    "chart_id": {
                        "type": "string",
                        "description": "Chart to generate: system_health, cluster_topology, pending_analysis, resource_map, job_lifecycle"
                    }
                },
                "required": ["chart_id"]
            },
            on_invoke_tool=generate_chart_wrapper,
        )
        
        # Debug: log tool info
        logger.info(f"Chart tool created: {chart_tool.name}")
        
        # Create main agent with REASONING model (qwen3-coder) - thinks before acting
        # Main agent uses wrapper FunctionTool for charts (hides artifact from LLM)
        all_tools = [analyze_tool, action_tool, confirm_tool, cancel_tool, check_pending_tool, chart_tool]
        logger.info(f"Registering {len(all_tools)} tools with main agent: {[getattr(t, 'name', str(t)) for t in all_tools]}")
        
        self.main_agent = Agent(
            name="Slurm Assistant",
            instructions=MAIN_AGENT_INSTRUCTIONS,
            model=self.reasoning_sdk_model,  # qwen3-coder for reasoning
            model_settings=REASONING_MODEL_SETTINGS,
            # NO mcp_servers - charts go through wrapper tool that hides artifacts
            tools=all_tools,
        )
        
        self._agents_initialized = True
        logger.info("Agents initialized with tool guardrails on dangerous MCP tools")
    
    async def _create_guarded_dangerous_tools(self) -> list[FunctionTool]:
        """
        Create FunctionTools for dangerous MCP tools that check SlurmContext.
        These wrap the MCP tool invocation with a context-based confirmation check.
        """
        import json
        
        guarded_tools = []
        
        # We need to connect to get tool schemas
        async with self._dangerous_mcp:
            # Get the list of dangerous MCP tools
            mcp_tools = await self._dangerous_mcp.list_tools()
            
            for mcp_tool in mcp_tools:
                if mcp_tool.name not in DANGEROUS_TOOLS:
                    continue
                
                # Create the FunctionTool with context check
                tool_name = mcp_tool.name
                tool_description = mcp_tool.description or f"Execute {tool_name}"
                tool_schema = mcp_tool.inputSchema if hasattr(mcp_tool, 'inputSchema') else {"type": "object", "properties": {}}
                
                # Capture tool_name, schema for proper arg extraction
                def make_invoke_fn(captured_name: str, captured_schema: dict):
                    async def invoke_dangerous_tool(ctx: ToolContext[SlurmContext], args_json: str) -> str:
                        """Queue dangerous action for batch confirmation."""
                        try:
                            args = {}
                            try:
                                args = json.loads(args_json) if args_json else {}
                            except:
                                pass
                            
                            # Build description from actual args provided
                            if args:
                                args_str = ", ".join(f"{k}={v}" for k, v in args.items())
                                description = f"{captured_name}({args_str})"
                            else:
                                description = f"{captured_name}()"
                            
                            # Add to pending queue
                            ctx.context.add_pending_action(captured_name, args, description)
                            
                            # Get total queued count
                            total_queued = len(ctx.context.get_pending_actions())
                            
                            logger.info(f"Queued dangerous action: {description} (total: {total_queued})")
                            return f"QUEUED: {description} ({total_queued} action(s) pending confirmation)"
                        except Exception as e:
                            logger.error(f"Error preparing {captured_name}: {e}")
                            return f"Error: {e}"
                    return invoke_dangerous_tool
                
                guarded_tool = FunctionTool(
                    name=tool_name,
                    description=tool_description,
                    params_json_schema=tool_schema,
                    on_invoke_tool=make_invoke_fn(tool_name, tool_schema),
                )
                guarded_tools.append(guarded_tool)
                logger.info(f"Created context-guarded FunctionTool for {tool_name}")
        
        return guarded_tools
    
    def _create_context(self) -> SlurmContext:
        """Create a new SlurmContext for a run."""
        return SlurmContext(session_id=self.session_id)
    
    async def run(self, user_message: str) -> Dict[str, Any]:
        """Run the agent system (non-streaming) with session memory and context."""
        try:
            logger.info(f"Processing: {user_message[:100]}...")
            await self._ensure_agents()
            
            # Get session for conversation history
            session = self._get_session()
            
            # Create context
            ctx = self._create_context()
            
            logger.info("Opening MCP connections...")
            # Note: _viz_mcp not needed here - chart wrapper uses direct HTTP
            async with self._analysis_mcp, self._action_mcp, self._dangerous_mcp:
                logger.info("MCP connections opened, running agent...")
                result = await Runner.run(
                    starting_agent=self.main_agent,
                    input=user_message,
                    session=session,
                    context=ctx,  # Pass SlurmContext
                    max_turns=100  # Increased from default 10 for complex multi-agent workflows
                )
                logger.info(f"Agent run completed: {result.last_agent.name}")
                
                # Get chart artifacts from context (stored by wrapper tool)
                chart_artifacts = ctx.chart_artifacts
                logger.info(f"Charts in context: {len(chart_artifacts)}")
                
                # Build response with chart artifacts appended
                final_message = str(result.final_output)
                for chart_code in chart_artifacts:
                    final_message += self._wrap_chart_artifact(chart_code)
                
                return {
                    "success": True,
                    "agent": result.last_agent.name,
                    "type": "response",
                    "message": final_message,
                    "executed": True,
                    "pending_actions": ctx.get_pending_actions()
                }
                
        except Exception as e:
            logger.error(f"Error: {e}")
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
        conversation_history: Optional[list] = None  # Kept for API compatibility, not used
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Run with streaming, session memory, and SlurmContext for confirmation.
        
        Simplified streaming - only emits:
        - status: Stage updates (Thinking, Analyzing, etc.)
        - final_answer: The final response to show to user
        - error: Any errors
        - done: Completion signal
        """
        try:
            logger.info(f"User message: {user_message[:100]}...")
            yield {"type": "status", "message": "Thinking..."}
            await self._ensure_agents()
            
            # Log available tools on main agent
            if self.main_agent and hasattr(self.main_agent, 'tools'):
                tool_names = [getattr(t, 'name', str(t)) for t in self.main_agent.tools]
                logger.info(f"Main agent tools: {tool_names}")
            
            session = self._get_session()
            ctx = self._create_context()
            logger.info(f"Created SlurmContext with id: {id(ctx)}")
            
            logger.info("Opening MCP connections for streaming...")
            # Note: _viz_mcp not needed here - chart wrapper uses direct HTTP
            async with self._analysis_mcp, self._action_mcp, self._dangerous_mcp:
                logger.info(f"MCP ready, starting streaming with session: {self.session_id}")
                
                result = Runner.run_streamed(
                    starting_agent=self.main_agent,
                    input=user_message,
                    session=session,
                    context=ctx
                )
                
                # Track state for stage updates
                current_agent = "Slurm Assistant"
                last_status = "Thinking..."
                # Note: Chart artifacts are stored in ctx.chart_artifacts by the wrapper tool
                
                # Process events for stage updates only
                async for event in result.stream_events():
                    # Skip raw response events
                    if event.type == "raw_response_event":
                        continue
                    
                    # Agent switch - update status
                    elif event.type == "agent_updated_stream_event":
                        new_agent = event.new_agent.name
                        logger.info(f"Agent switch: {current_agent} -> {new_agent}")
                        if new_agent != current_agent:
                            current_agent = new_agent
                            if "Analysis" in new_agent:
                                status = "Analyzing cluster..."
                            elif "Action" in new_agent:
                                status = "Executing action..."
                            else:
                                status = "Processing..."
                            
                            if status != last_status:
                                last_status = status
                                yield {"type": "status", "message": status}
                    
                    # Run items - tool calls and messages
                    elif event.type == "run_item_stream_event":
                        item = event.item
                        logger.debug(f"Run item: {item.type}")
                        
                        if item.type == "tool_call_item":
                            # Get tool name from raw_item
                            tool_name = getattr(item.raw_item, 'name', '') if hasattr(item, 'raw_item') else ''
                            tool_args = getattr(item.raw_item, 'arguments', '') if hasattr(item, 'raw_item') else ''
                            logger.info(f"Tool call: {tool_name}, args: {str(tool_args)[:100]}")
                            
                            if tool_name:
                                # Check if analyze_cluster is being called for web search
                                if tool_name == "analyze_cluster":
                                    status = "Gathering cluster data..."
                                elif tool_name == "manage_jobs":
                                    status = "Managing jobs..."
                                elif tool_name == "confirm_action":
                                    status = "Confirming action..."
                                elif tool_name == "cancel_action":
                                    status = "Cancelling action..."
                                elif tool_name == "check_pending_actions":
                                    status = "Checking pending actions..."
                                elif tool_name == "generate_chart":
                                    status = "Generating chart..."
                                else:
                                    status = f"Running {tool_name}..."
                                
                                if status != last_status:
                                    last_status = status
                                    yield {"type": "status", "message": status}
                        
                        elif item.type == "tool_call_output_item":
                            # Check tool output for subagent activity
                            output = item.output if hasattr(item, 'output') else ""
                            output_str = str(output)
                            logger.info(f"Tool output (first 300): {output_str[:300]}")
                            
                            # Detect web_search by [WEB_SEARCH]: marker from tool_use_behavior
                            if "[WEB_SEARCH]:" in output_str:
                                if last_status != "Searching web...":
                                    last_status = "Searching web..."
                                    yield {"type": "status", "message": "Searching web..."}
                                
                                # Extract URLs from web search results
                                import re
                                url_pattern = r'URL:\s*(https?://[^\s\n\'"]+)'
                                urls = re.findall(url_pattern, output_str)
                                if urls:
                                    logger.info(f"Web search found {len(urls)} URLs: {urls[:3]}")
                                    yield {"type": "web_results", "urls": urls[:5]}
                            # Detect run_analysis script execution
                            elif "[run_analysis]:" in output_str:
                                if last_status != "Running analysis script...":
                                    last_status = "Running analysis script..."
                                    yield {"type": "status", "message": "Running analysis script..."}
                        
                        elif item.type == "message_output_item":
                            # Final message from main agent
                            if current_agent == "Slurm Assistant":
                                # Emit status before final answer (only once)
                                if last_status != "Generating response...":
                                    last_status = "Generating response..."
                                    yield {"type": "status", "message": "Generating response..."}
                                
                                content = ItemHelpers.text_message_output(item)
                                logger.info(f"LLM response (first 200 chars): {content[:200] if content else 'empty'}")
                                
                                # Get chart artifacts from context (stored by wrapper tool)
                                chart_artifacts = ctx.chart_artifacts if ctx else []
                                logger.info(f"Final message - charts in context: {len(chart_artifacts)}, ctx id: {id(ctx)}")
                                
                                if content:
                                    clean_content = self._clean_hallucinated_calls(content)
                                    
                                    if clean_content.strip():
                                        # Append chart artifacts to final answer
                                        full_response = clean_content
                                        for i, chart_code in enumerate(chart_artifacts):
                                            logger.info(f"Appending chart {i+1}/{len(chart_artifacts)}, len={len(chart_code)}")
                                            full_response += self._wrap_chart_artifact(chart_code)
                                        
                                        logger.info(f"Final response length: {len(full_response)}")
                                        yield {"type": "final_answer", "message": full_response}
                
                yield {"type": "done"}
                
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            import traceback
            traceback.print_exc()
            
            error_msg = str(e)
            
            # Handle corrupted history - clear session and suggest retry
            if "invalid tool call arguments" in error_msg.lower():
                logger.warning(f"Corrupted tool call in history detected, clearing session: {self.session_id}")
                try:
                    await self.clear_session()
                    error_msg = "I had a hiccup with my memory. I've cleared my context - please try your request again."
                except Exception as clear_err:
                    logger.error(f"Failed to clear session: {clear_err}")
                    error_msg = "I encountered an issue. Please start a new conversation."
            elif "Invalid JSON" in error_msg:
                error_msg = "There was a technical issue with my response. Please try rephrasing your question."
            
            yield {"type": "error", "message": error_msg}
    
    def _clean_hallucinated_calls(self, text: str) -> str:
        """Remove hallucinated XML function calls from model output."""
        import re
        # Remove <function=...>...</tool_call> patterns
        text = re.sub(r'<function=[^>]*>.*?</tool_call>', '', text, flags=re.DOTALL)
        # Remove standalone tags
        text = re.sub(r'</?function[^>]*>', '', text)
        text = re.sub(r'</?parameter[^>]*>', '', text)
        text = re.sub(r'</?tool_call>', '', text)
        return text.strip()
    
    def _wrap_chart_artifact(self, mermaid_code: str) -> str:
        """
        Wrap Mermaid diagram for OpenWebUI native rendering.
        
        OpenWebUI has built-in Mermaid support with pan/zoom capabilities.
        Charts are wrapped in ```mermaid code blocks which OpenWebUI renders
        as interactive SVG diagrams.
        """
        # OpenWebUI renders ```mermaid blocks as interactive SVG with pan/zoom
        # No visible markers - we detect mermaid blocks directly for filtering
        return f"\n\n```mermaid\n{mermaid_code}\n```"
    
    @staticmethod
    def strip_chart_artifacts(text: str) -> str:
        """Remove chart artifacts (mermaid blocks) from text for history filtering."""
        if not text:
            return text
        # Remove mermaid code blocks from history to keep context clean
        pattern = r'```mermaid\n.*?```'
        return re.sub(pattern, '', text, flags=re.DOTALL).strip()
    
    async def clear_session(self):
        """Clear conversation history for this session."""
        if self._session:
            await self._session.clear_session()
            logger.info(f"Cleared session history for: {self.session_id}")
    
    async def disconnect(self):
        """Clean up."""
        self._analysis_mcp = None
        self._action_mcp = None
        self._dangerous_mcp = None
        self._session = None
        self._agents_initialized = False
    
    async def __aenter__(self):
        await self._ensure_agents()
        return self
    
    async def __aexit__(self, *args):
        await self.disconnect()


# ============ Convenience Functions ============

async def run_multi_agent(message: str, mcp_url: str = "http://localhost:3002") -> Dict[str, Any]:
    """Quick one-shot execution."""
    system = SlurmMultiAgentSystem(mcp_url=mcp_url)
    try:
        return await system.run(message)
    finally:
        await system.disconnect()


async def run_multi_agent_streaming(
    message: str, 
    conversation_history: Optional[list] = None, 
    mcp_url: str = "http://localhost:3002"
) -> AsyncGenerator[Dict[str, Any], None]:
    """Quick one-shot streaming execution."""
    system = SlurmMultiAgentSystem(mcp_url=mcp_url)
    try:
        async for event in system.run_streaming(message, conversation_history):
            yield event
    finally:
        await system.disconnect()
