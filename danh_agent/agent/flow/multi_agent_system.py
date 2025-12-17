"""
Multi-Agent System with Handoffs (OpenAI Swarm Pattern)

Architecture:
1. User Chat Agent - Friendly interface, learns from Slurm agent outputs
2. Terminal Agent - Direct command execution (squeue, sinfo, etc.)
3. Slurm Planning Agent - Generates structured command sequences  
4. Execution Agent - Validates and executes commands
5. ReAct Agent - Complex reasoning with Think → Act → Observe loop

Features:
- RunContext pattern from OpenAI Agents SDK for state sharing
- Typed context object shared across all agents and tools
- Knowledge base for learning from interactions
- Two-level confirmation: Chat (handoffs) and Tool (execution)

Agents can hand off to each other dynamically!
"""
import asyncio
from typing import List, Dict, Any, Optional, Callable, TypeVar, Generic, Awaitable
from pydantic import BaseModel, Field
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
import logging

from utils.openai_client import OllamaClient
from utils.slurm_commands import SlurmCommandSequence, SlurmCommandBuilder
from flow.terminal_agent import TerminalAgent, CommandType
from flow.react_agent import FullAgenticSystem as ReActSystem

logger = logging.getLogger(__name__)


# ============ Confirmation Types ============

class ConfirmationType(str, Enum):
    """Types of confirmations in the system"""
    HANDOFF = "handoff"           # Before agent transfer
    TOOL_EXECUTION = "tool"       # Before running tools
    DANGEROUS_COMMAND = "danger"  # Before dangerous Slurm commands (scancel, etc.)
    SCRIPT_EXECUTION = "script"   # Before running generated scripts


class ConfirmationRequest(BaseModel):
    """Request for user confirmation"""
    request_id: str = Field(default_factory=lambda: datetime.now().strftime("%H%M%S%f"))
    confirmation_type: ConfirmationType
    title: str
    description: str
    details: Dict[str, Any] = {}
    requires_confirmation: bool = True
    timestamp: datetime = Field(default_factory=datetime.now)


class ConfirmationResponse(BaseModel):
    """User's response to confirmation request"""
    request_id: str
    confirmed: bool
    user_message: Optional[str] = None
    modified_input: Optional[str] = None  # User can modify before confirm


class ConfirmationManager:
    """
    Manages confirmations for both chat (handoffs) and tool execution.
    
    Two confirmation levels:
    1. CHAT CONFIRMATION - Before agent handoffs (optional, for visibility)
    2. TOOL CONFIRMATION - Before dangerous command execution (required for safety)
    
    Modes:
    - auto: Auto-confirm everything (for testing/demos)
    - interactive: Ask user via console input
    - callback: Use async callback function (for API/UI integration)
    - manual: Wait for explicit confirmation via API
    """
    
    def __init__(
        self,
        mode: str = "auto",
        confirm_handoffs: bool = False,  # Confirm agent transfers?
        confirm_tools: bool = True,      # Confirm tool execution?
        confirm_dangerous: bool = True,  # Always confirm dangerous commands
    ):
        self.mode = mode
        self.confirm_handoffs = confirm_handoffs
        self.confirm_tools = confirm_tools
        self.confirm_dangerous = confirm_dangerous
        
        # Dangerous commands that always need confirmation
        self.dangerous_commands = [
            'scancel', 'scontrol update', 'scontrol hold', 
            'scontrol release', 'scontrol suspend', 'scontrol resume',
            'sbatch'  # Job submission
        ]
        
        # Pending requests and responses
        self.pending: Dict[str, ConfirmationRequest] = {}
        self.responses: Dict[str, ConfirmationResponse] = {}
        
        # For async confirmations
        self._futures: Dict[str, asyncio.Future] = {}
        
        # Callback for external confirmation (API/UI)
        self._callback: Optional[Callable[[ConfirmationRequest], Awaitable[ConfirmationResponse]]] = None
    
    def set_callback(self, callback: Callable[[ConfirmationRequest], Awaitable[ConfirmationResponse]]):
        """Set callback for API/UI-based confirmation"""
        self._callback = callback
        self.mode = "callback"
    
    def is_dangerous(self, command: str) -> bool:
        """Check if command is dangerous and needs confirmation"""
        cmd_lower = command.lower()
        return any(dc in cmd_lower for dc in self.dangerous_commands)
    
    async def request_confirmation(
        self,
        confirmation_type: ConfirmationType,
        title: str,
        description: str,
        details: Dict[str, Any] = None
    ) -> ConfirmationResponse:
        """
        Request confirmation based on type and mode
        
        Returns:
            ConfirmationResponse with user's decision
        """
        request = ConfirmationRequest(
            confirmation_type=confirmation_type,
            title=title,
            description=description,
            details=details or {}
        )
        
        # Check if confirmation is needed
        needs_confirm = False
        if confirmation_type == ConfirmationType.HANDOFF and self.confirm_handoffs:
            needs_confirm = True
        elif confirmation_type == ConfirmationType.TOOL_EXECUTION and self.confirm_tools:
            needs_confirm = True
        elif confirmation_type == ConfirmationType.DANGEROUS_COMMAND and self.confirm_dangerous:
            needs_confirm = True
        elif confirmation_type == ConfirmationType.SCRIPT_EXECUTION:
            needs_confirm = True
        
        if not needs_confirm:
            return ConfirmationResponse(request_id=request.request_id, confirmed=True)
        
        # Handle based on mode
        if self.mode == "auto":
            return ConfirmationResponse(request_id=request.request_id, confirmed=True)
        
        elif self.mode == "interactive":
            return await self._interactive_confirm(request)
        
        elif self.mode == "callback" and self._callback:
            return await self._callback(request)
        
        elif self.mode == "manual":
            return await self._manual_confirm(request)
        
        # Default: auto-confirm
        return ConfirmationResponse(request_id=request.request_id, confirmed=True)
    
    async def _interactive_confirm(self, request: ConfirmationRequest) -> ConfirmationResponse:
        """Interactive console confirmation"""
        print(f"\n{'⚠️' * 3} CONFIRMATION REQUIRED {'⚠️' * 3}")
        print(f"Type: {request.confirmation_type.value.upper()}")
        print(f"Title: {request.title}")
        print(f"Description: {request.description}")
        if request.details:
            print(f"Details: {json.dumps(request.details, indent=2)}")
        
        response = input("\nConfirm? (y/n/m to modify): ").strip().lower()
        
        if response == 'y':
            return ConfirmationResponse(request_id=request.request_id, confirmed=True)
        elif response == 'm':
            modified = input("Enter modified input: ").strip()
            return ConfirmationResponse(
                request_id=request.request_id, 
                confirmed=True, 
                modified_input=modified
            )
        else:
            return ConfirmationResponse(
                request_id=request.request_id, 
                confirmed=False,
                user_message="User declined"
            )
    
    async def _manual_confirm(self, request: ConfirmationRequest) -> ConfirmationResponse:
        """Wait for manual confirmation via API"""
        self.pending[request.request_id] = request
        future = asyncio.get_event_loop().create_future()
        self._futures[request.request_id] = future
        
        try:
            # Wait for external confirmation (with timeout)
            response = await asyncio.wait_for(future, timeout=300)
            return response
        except asyncio.TimeoutError:
            return ConfirmationResponse(
                request_id=request.request_id,
                confirmed=False,
                user_message="Confirmation timed out"
            )
        finally:
            self.pending.pop(request.request_id, None)
            self._futures.pop(request.request_id, None)
    
    def confirm(self, request_id: str, confirmed: bool, message: str = None, modified: str = None):
        """External confirmation (for API)"""
        if request_id in self._futures:
            response = ConfirmationResponse(
                request_id=request_id,
                confirmed=confirmed,
                user_message=message,
                modified_input=modified
            )
            self._futures[request_id].set_result(response)
            self.responses[request_id] = response


# ============ Agent Context (OpenAI SDK Pattern) ============

@dataclass
class AgentContext:
    """
    Shared context across all agents during a run.
    Following OpenAI Agents SDK RunContext pattern.
    
    This context is NOT sent to the LLM - it's for local state sharing.
    """
    # User information
    user_id: str = "default"
    session_id: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S"))
    
    # Execution state
    current_agent: str = ""
    handoff_chain: List[str] = field(default_factory=list)
    
    # Generated artifacts (passed between agents)
    generated_scripts: List[str] = field(default_factory=list)
    command_sequences: List[Dict] = field(default_factory=list)
    terminal_outputs: List[Dict] = field(default_factory=list)
    
    # Knowledge accumulated during run
    explanations: List[Dict] = field(default_factory=list)
    validations: List[Dict] = field(default_factory=list)
    
    # User preferences learned
    preferences: Dict[str, Any] = field(default_factory=dict)
    
    # Error tracking
    errors: List[Dict] = field(default_factory=list)
    
    def add_handoff(self, from_agent: str, to_agent: str):
        """Track agent handoffs"""
        self.handoff_chain.append(f"{from_agent} → {to_agent}")
        self.current_agent = to_agent
    
    def add_script(self, script: str, description: str = ""):
        """Add generated script"""
        self.generated_scripts.append({
            "script": script,
            "description": description,
            "timestamp": datetime.now().isoformat(),
            "agent": self.current_agent
        })
    
    def add_terminal_output(self, command: str, output: str, success: bool = True):
        """Add terminal command output"""
        self.terminal_outputs.append({
            "command": command,
            "output": output,
            "success": success,
            "timestamp": datetime.now().isoformat()
        })
    
    def add_explanation(self, topic: str, content: str):
        """Add explanation for learning"""
        self.explanations.append({
            "topic": topic,
            "content": content,
            "agent": self.current_agent
        })
    
    def add_error(self, error: str, context: str = ""):
        """Track errors for debugging"""
        self.errors.append({
            "error": error,
            "context": context,
            "agent": self.current_agent,
            "timestamp": datetime.now().isoformat()
        })
    
    def get_summary(self) -> Dict[str, Any]:
        """Get context summary for debugging/logging"""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "current_agent": self.current_agent,
            "handoff_chain": self.handoff_chain,
            "scripts_generated": len(self.generated_scripts),
            "commands_run": len(self.terminal_outputs),
            "errors": len(self.errors)
        }


class RunContextWrapper(Generic[TypeVar('T')]):
    """
    Wrapper for context during agent runs.
    Following OpenAI Agents SDK pattern.
    
    Provides typed access to the context object.
    """
    def __init__(self, context: 'T'):
        self._context = context
    
    @property
    def context(self) -> 'T':
        """Access the underlying context object"""
        return self._context


# ============ Agent Models ============

class Agent(BaseModel):
    """Agent with instructions, tools, and handoff capabilities"""
    name: str
    model: str = "qwen3-coder:latest"
    instructions: str
    tools: List[Callable] = []
    
    class Config:
        arbitrary_types_allowed = True


class Response(BaseModel):
    """Response from agent execution"""
    agent: Agent
    messages: List[Dict[str, Any]]
    metadata: Dict[str, Any] = {}


# ============ Main Orchestrator ============

class MultiAgentOrchestrator:
    """
    Orchestrates multiple agents with handoff capabilities
    
    Uses OpenAI Swarm pattern: agents can transfer conversations to each other
    Uses RunContext pattern: shared typed context across all agents
    
    Two-level confirmation:
    - Chat level: Confirm before agent handoffs (optional)
    - Tool level: Confirm before dangerous command execution (configurable)
    """
    
    def __init__(
        self, 
        user_id: str = "default",
        confirmation_mode: str = "auto",  # auto, interactive, callback, manual
        confirm_handoffs: bool = False,
        confirm_dangerous: bool = True
    ):
        self.client = OllamaClient(model="qwen3-coder:latest")
        
        # Create run context (OpenAI SDK pattern)
        self._context = AgentContext(user_id=user_id)
        self.ctx = RunContextWrapper(self._context)
        
        # Create confirmation manager
        self.confirmation = ConfirmationManager(
            mode=confirmation_mode,
            confirm_handoffs=confirm_handoffs,
            confirm_tools=True,
            confirm_dangerous=confirm_dangerous
        )
        
        # Legacy knowledge base (now backed by context)
        self.knowledge_base: Dict[str, List[Dict]] = {
            "slurm_commands": [],
            "user_interactions": [],
            "executions": []
        }
        
        # Initialize agents
        self.chat_agent = self._create_chat_agent()
        self.slurm_agent = self._create_slurm_agent()
        self.execution_agent = self._create_execution_agent()
        self.terminal_agent = self._create_terminal_agent()
        self.react_agent = self._create_react_agent()
        
        # Terminal agent instance for direct command execution
        self._terminal_executor = TerminalAgent(model="qwen3-coder:latest", simulate=True)
        
        # ReAct system instance for complex reasoning tasks
        self._react_system = ReActSystem(model="qwen3-coder:latest", interactive=False)
        
    def _create_chat_agent(self) -> Agent:
        """
        User-facing chat agent
        - Friendly conversational interface
        - Learns from Slurm agent outputs
        - Can answer questions about Slurm
        - Hands off to Slurm agent for command generation
        """
        instructions = """You are a friendly Slurm assistant that helps users interact with HPC clusters.

Your role:
- Have natural conversations with users about their Slurm needs
- Answer questions about Slurm commands, job management, and cluster usage
- Learn from past interactions stored in your knowledge base
- When user needs actual commands generated, transfer to Slurm Planning Agent

Available knowledge:
- Previous Slurm command sequences
- User interaction history
- Execution results

Communication style:
- Be conversational and helpful
- Explain Slurm concepts in simple terms
- Suggest best practices
- Always confirm before executing commands

When to transfer:
- To Terminal Agent: Simple queries like "show my jobs", "check queue", "cluster status", "cancel job X"
- To Slurm Planning Agent: Complex job submissions with resources, sbatch scripts
- To ReAct Agent: Complex multi-step reasoning tasks, debugging failed jobs, "why did my job fail", workflow troubleshooting
- User describes a task that needs command execution (e.g., "I need to submit a job")
"""
        return Agent(
            name="Chat Agent",
            instructions=instructions,
            tools=[
                self.transfer_to_terminal_agent,
                self.transfer_to_slurm_agent,
                self.transfer_to_react_agent,
                self.search_knowledge_base,
                self.explain_slurm_concept
            ]
        )
    
    def _create_slurm_agent(self) -> Agent:
        """
        Slurm command planning agent
        - Generates structured command sequences
        - Validates requirements
        - Hands off to execution agent or back to chat
        """
        instructions = """You are a Slurm command planning expert.

Your role:
- Generate precise, structured command sequences for Slurm tasks
- Validate resource requirements
- Provide detailed explanations of what commands will do
- Hand off to Execution Agent when commands are ready

Command generation rules:
- Always use proper Slurm command types (sbatch, squeue, scancel, etc.)
- Include all necessary parameters (nodes, GPUs, memory, time limits)
- Add clear descriptions of expected outcomes
- Validate before execution

When to transfer:
- Back to Chat Agent: User wants to discuss or ask questions
- To Execution Agent: Commands are validated and ready to execute
"""
        return Agent(
            name="Slurm Planning Agent", 
            instructions=instructions,
            tools=[
                self.generate_slurm_commands,
                self.transfer_to_chat_agent,
                self.transfer_to_execution_agent
            ]
        )
    
    def _create_execution_agent(self) -> Agent:
        """
        Execution agent
        - Validates commands one final time
        - Compiles to shell scripts
        - Optionally executes (with user confirmation)
        - Records results in knowledge base
        """
        instructions = """You are a Slurm execution specialist.

Your role:
- Final validation of command sequences
- Compile commands to executable shell scripts
- Execute commands (with user confirmation)
- Record results for learning

Safety checks:
- Validate all commands before execution
- Warn about destructive operations (scancel, scontrol update)
- Require explicit confirmation for job submissions
- Log all executions

When to transfer:
- Back to Chat Agent: User wants to discuss results or ask questions
- Back to Slurm Agent: Commands need modification
"""
        return Agent(
            name="Execution Agent",
            instructions=instructions,
            tools=[
                self.validate_and_execute,
                self.save_to_knowledge_base,
                self.transfer_to_chat_agent,
                self.transfer_to_slurm_agent
            ]
        )
    
    def _create_terminal_agent(self) -> Agent:
        """
        Terminal agent for direct command execution
        - Like VS Code Copilot terminal - runs simple commands immediately
        - Handles: squeue, sinfo, sacct, scancel, scontrol show, sprio, sshare
        - With confirmation for dangerous operations
        """
        instructions = """You are a terminal-like Slurm command executor.

Your role:
- Execute simple Slurm commands DIRECTLY (no scripts needed)
- Fast, responsive command execution
- Show command output immediately
- Handle queries like "show my jobs", "check cluster status", "cancel job 12345"

Commands you handle DIRECTLY:
- squeue (show jobs in queue)
- sinfo (show cluster/partition info)  
- sacct (show job history)
- scancel (cancel jobs) - WITH CONFIRMATION
- scontrol show (show job/node details)
- sprio (show job priorities)
- sshare (show fair share info)

Workflow:
1. Understand user's natural language request
2. Determine the appropriate Slurm command
3. Execute directly (confirm if dangerous)
4. Show output

When to transfer:
- To Slurm Planning Agent: Complex sbatch jobs that need scripts
- To Chat Agent: User wants explanations or has questions

IMPORTANT: For simple queries, just execute. Don't overthink it.
"show my jobs" → squeue -u $USER → show output. Done."""
        return Agent(
            name="Terminal Agent",
            instructions=instructions,
            tools=[
                self.execute_terminal_command,
                self.transfer_to_slurm_agent,
                self.transfer_to_react_agent,
                self.transfer_to_chat_agent
            ]
        )
    
    def _create_react_agent(self) -> Agent:
        """
        ReAct agent for complex reasoning tasks
        - Think → Act → Observe loop
        - Multi-step problem solving
        - Self-correction on failures
        - Handles: debugging, troubleshooting, complex workflows
        """
        instructions = """You are an advanced reasoning agent using the ReAct pattern (Reasoning + Acting).

Your role:
- Handle complex multi-step tasks that require reasoning
- Debug and troubleshoot job failures
- Create comprehensive workflows with validation
- Learn from observations and adjust approach

ReAct Loop:
1. THINK: Analyze the situation and plan next step
2. ACT: Execute an action (explain, generate, validate, execute, review)
3. OBSERVE: Learn from the result
4. Repeat until goal is achieved

Available actions:
- explain: Explain Slurm concepts in detail
- generate_commands: Create command sequences
- validate: Validate scripts/commands
- execute: Save/run commands
- review: Review work and suggest improvements
- replan: Change approach if needed

When to transfer:
- To Terminal Agent: Simple direct commands
- To Slurm Planning Agent: Standard job script generation
- To Chat Agent: Simple Q&A

Use me for:
- "Why did my job fail?" - Investigate and diagnose
- "Help me set up a complete workflow" - Multi-step with validation
- "Debug this job configuration" - Iterative troubleshooting
- "Optimize my job script" - Analysis and improvement"""
        return Agent(
            name="ReAct Agent",
            instructions=instructions,
            tools=[
                self.run_react_reasoning,
                self.transfer_to_terminal_agent,
                self.transfer_to_slurm_agent,
                self.transfer_to_chat_agent
            ]
        )
    
    # ============ Handoff Functions (with Context Tracking) ============
    
    def transfer_to_chat_agent(self) -> Agent:
        """Transfer conversation to Chat Agent for Q&A and discussion"""
        self.ctx.context.add_handoff(self.ctx.context.current_agent, "Chat Agent")
        logger.info(f"🔄 Transferring to Chat Agent (chain: {len(self.ctx.context.handoff_chain)})")
        return self.chat_agent
    
    def transfer_to_slurm_agent(self) -> Agent:
        """Transfer to Slurm Planning Agent for command generation"""
        self.ctx.context.add_handoff(self.ctx.context.current_agent, "Slurm Planning Agent")
        logger.info(f"🔄 Transferring to Slurm Planning Agent (chain: {len(self.ctx.context.handoff_chain)})")
        return self.slurm_agent
    
    def transfer_to_execution_agent(self) -> Agent:
        """Transfer to Execution Agent to run commands"""
        self.ctx.context.add_handoff(self.ctx.context.current_agent, "Execution Agent")
        logger.info(f"🔄 Transferring to Execution Agent (chain: {len(self.ctx.context.handoff_chain)})")
        return self.execution_agent
    
    def transfer_to_terminal_agent(self) -> Agent:
        """Transfer to Terminal Agent for direct command execution (squeue, sinfo, scancel, etc.)"""
        self.ctx.context.add_handoff(self.ctx.context.current_agent, "Terminal Agent")
        logger.info(f"🔄 Transferring to Terminal Agent (chain: {len(self.ctx.context.handoff_chain)})")
        return self.terminal_agent
    
    def transfer_to_react_agent(self) -> Agent:
        """Transfer to ReAct Agent for complex reasoning tasks (debugging, troubleshooting, multi-step workflows)"""
        self.ctx.context.add_handoff(self.ctx.context.current_agent, "ReAct Agent")
        logger.info(f"🔄 Transferring to ReAct Agent (chain: {len(self.ctx.context.handoff_chain)})")
        return self.react_agent
    
    # ============ Tool Functions (with Context) ============
    
    async def run_react_reasoning(self, goal: str) -> str:
        """
        Run ReAct reasoning loop for complex multi-step tasks
        
        Args:
            goal: The complex goal to achieve (e.g., "debug why job 12345 failed", "set up a complete GPU training workflow")
            
        Returns:
            Summary of reasoning steps and results
        """
        logger.info(f"🧠 ReAct reasoning: {goal}")
        
        # Run the ReAct loop
        result = await self._react_system.run_react_loop(goal, max_steps=8)
        
        # Store in context
        react_context = result.get("context", {})
        for script in react_context.get("generated_scripts", []):
            self.ctx.context.add_script(script, f"ReAct generated for: {goal[:50]}")
        for exp in react_context.get("explanations", []):
            self.ctx.context.add_explanation(exp.get("topic", ""), exp.get("content", ""))
        
        # Format response
        output = f"🎯 **Goal**: {goal}\n\n"
        output += f"**Steps taken**: {result['steps']}\n\n"
        
        # Summarize execution context
        if react_context.get("generated_scripts"):
            output += f"📜 **Scripts generated**: {len(react_context['generated_scripts'])}\n"
        if react_context.get("explanations"):
            output += f"💡 **Explanations**: {len(react_context['explanations'])}\n"
        if react_context.get("validations"):
            output += f"✅ **Validations**: {len(react_context['validations'])}\n"
        
        # Include last few steps summary
        history = result.get("history", [])
        if history:
            output += "\n**Reasoning trace**:\n"
            for i, step in enumerate(history[-3:], 1):
                output += f"\n{i}. 💭 {step['thought'][:100]}...\n"
                output += f"   🎬 Action: {step['action']}\n"
        
        return output
    
    async def execute_terminal_command(self, user_request: str) -> str:
        """
        Execute a Slurm command directly via terminal agent
        
        Args:
            user_request: Natural language request like "show my jobs" or "check cluster status"
            
        Returns:
            Command output or explanation
        """
        logger.info(f"🖥️  Terminal execution: {user_request}")
        
        # Use the terminal executor
        result = await self._terminal_executor.process(user_request)
        
        # Check if dangerous command needs confirmation
        command = result.get("command", "")
        if command and self.confirmation.is_dangerous(command):
            confirm_response = await self.confirmation.request_confirmation(
                confirmation_type=ConfirmationType.DANGEROUS_COMMAND,
                title=f"Dangerous Command: {command.split()[0]}",
                description=f"Execute: {command}",
                details={"command": command, "explanation": result.get("explanation", "")}
            )
            
            if not confirm_response.confirmed:
                return f"⏹️ Command cancelled by user: {command}"
            
            # User may have modified the command
            if confirm_response.modified_input:
                result = await self._terminal_executor.process(confirm_response.modified_input)
        
        # Store in context
        if result.get("command"):
            self.ctx.context.add_terminal_output(
                command=result.get("command", ""),
                output=result.get("output", ""),
                success=result.get("status") == "executed"
            )
        
        # Format response
        if result.get("status") == "executed":
            output = f"💻 Command: `{result.get('command')}`\n"
            output += f"📝 {result.get('explanation', '')}\n\n"
            output += "```\n"
            output += result.get("output", "(no output)")
            output += "\n```"
            if result.get("simulated"):
                output += "\n_(simulated output)_"
            return output
        
        elif result.get("status") == "cancelled":
            return f"⏹️ Command cancelled: {result.get('message')}"
        
        elif result.get("status") == "failed":
            self.ctx.context.add_error(result.get("error", "Unknown error"), f"Terminal: {user_request}")
            return f"❌ Error: {result.get('error')}"
        
        elif result.get("status") == "answered":
            self.ctx.context.add_explanation(user_request, result.get('message', result.get('explanation', '')))
            return f"💡 {result.get('message', result.get('explanation', ''))}"
        
        elif result.get("status") == "script_generated":
            self.ctx.context.add_script(result.get('script', ''), f"Terminal generated: {user_request}")
            return f"📜 This requires a script. Transferring to Slurm Planning Agent.\n\nScript preview:\n```bash\n{result.get('script', '')[:500]}...\n```"
        
        return f"Processed: {result}"
    
    def search_knowledge_base(self, query: str) -> str:
        """
        Search knowledge base and context for relevant Slurm information
        
        Args:
            query: Search query about Slurm commands or past interactions
        """
        logger.info(f"🔍 Searching knowledge base: {query}")
        
        results = []
        
        # Search context terminal outputs (new pattern)
        for output in self.ctx.context.terminal_outputs[-10:]:
            if query.lower() in output.get("command", "").lower():
                results.append({
                    "type": "terminal_output",
                    "command": output["command"],
                    "success": output["success"]
                })
        
        # Search context explanations
        for exp in self.ctx.context.explanations[-10:]:
            if query.lower() in exp.get("topic", "").lower():
                results.append({
                    "type": "explanation",
                    "topic": exp["topic"],
                    "agent": exp.get("agent", "")
                })
        
        # Search legacy command history
        for entry in self.knowledge_base["slurm_commands"][-10:]:
            if query.lower() in entry.get("description", "").lower():
                results.append({
                    "type": "command",
                    "description": entry["description"],
                    "commands": entry.get("command_count", 0)
                })
        
        # Search user interactions
        for entry in self.knowledge_base["user_interactions"][-10:]:
            if query.lower() in entry.get("request", "").lower():
                results.append({
                    "type": "interaction",
                    "request": entry["request"],
                    "outcome": entry.get("outcome", "unknown")
                })
        
        if not results:
            return f"No relevant information found for: {query}"
        
        return json.dumps(results, indent=2)
    
    def explain_slurm_concept(self, concept: str) -> str:
        """
        Explain a Slurm concept in simple terms
        
        Args:
            concept: Slurm concept to explain (e.g., 'sbatch', 'partition', 'gres')
        """
        explanations = {
            "sbatch": "sbatch submits a batch job script to Slurm. It queues your job and runs it when resources are available.",
            "squeue": "squeue shows the current job queue - what jobs are running or waiting.",
            "scancel": "scancel cancels/terminates jobs. Use the job ID to specify which job.",
            "sinfo": "sinfo displays information about cluster partitions and node status.",
            "partition": "A partition is a job queue with specific resource limits (CPUs, memory, time).",
            "gres": "Generic RESource - used to request special resources like GPUs (e.g., gres=gpu:4 for 4 GPUs).",
            "nodes": "Physical machines in the cluster. Jobs can run on one or multiple nodes.",
            "ntasks": "Number of parallel tasks/processes to launch for your job.",
            "cpus-per-task": "Number of CPU cores allocated to each task.",
            "mem": "Memory (RAM) allocated to your job (e.g., 32GB, 64000M).",
            "time": "Maximum wall-clock time for the job (format: HH:MM:SS or days-HH:MM:SS).",
        }
        
        concept_lower = concept.lower().replace("-", "_").replace(" ", "_")
        
        for key, explanation in explanations.items():
            if concept_lower in key or key in concept_lower:
                return f"**{concept}**: {explanation}"
        
        return f"I don't have a specific explanation for '{concept}', but I can help you understand Slurm concepts. Try asking about: sbatch, squeue, partitions, GPUs, memory, or time limits."
    
    async def generate_slurm_commands(self, user_request: str) -> str:
        """
        Generate structured Slurm command sequence
        
        Args:
            user_request: What the user wants to accomplish
        """
        logger.info(f"⚙️  Generating Slurm commands for: {user_request}")
        
        # Import here to avoid circular dependency
        from flow.slurm_structured_agent import SlurmStructuredAgent
        
        # Use the existing structured agent
        agent = SlurmStructuredAgent(model=self.slurm_agent.model)
        result = await agent.plan_only(user_request)
        
        # Store in knowledge base
        self.knowledge_base["slurm_commands"].append({
            "request": user_request,
            "description": result["sequence"]["description"],
            "command_count": len(result["sequence"]["commands"])
        })
        
        # Return summary
        sequence = SlurmCommandSequence(**result["sequence"])
        summary = f"Generated {len(sequence.commands)} commands:\n"
        summary += f"Description: {sequence.description}\n\n"
        for i, cmd in enumerate(sequence.commands, 1):
            cmd_type = cmd.__class__.__name__.replace('Command', '')
            summary += f"{i}. {cmd_type}\n"
        
        return summary
    
    def validate_and_execute(self, commands_json: str) -> str:
        """
        Validate and optionally execute Slurm command sequence
        
        Args:
            commands_json: JSON string of command sequence
        """
        logger.info("✅ Validating command sequence")
        
        try:
            # Parse sequence
            sequence_dict = json.loads(commands_json)
            sequence = SlurmCommandSequence(**sequence_dict)
            
            # Validate
            builder = SlurmCommandBuilder()
            validation = builder.validate_sequence(sequence)
            
            if not validation["valid"]:
                return f"❌ Validation failed:\n" + "\n".join(validation["errors"])
            
            # Compile
            script = builder.compile_to_shell(sequence)
            script_path = "/tmp/slurm_generated.sh"
            builder.save_script(sequence, script_path)
            
            # Store execution record
            self.knowledge_base["executions"].append({
                "description": sequence.description,
                "commands": len(sequence.commands),
                "script_path": script_path,
                "status": "generated"
            })
            
            return f"✅ Validated successfully!\n\nScript saved to: {script_path}\n\nTo execute: bash {script_path}"
            
        except Exception as e:
            return f"❌ Error: {e}"
    
    def save_to_knowledge_base(self, category: str, data: str) -> str:
        """
        Save information to knowledge base for learning
        
        Args:
            category: Category (slurm_commands, user_interactions, executions)
            data: JSON string of data to save
        """
        try:
            entry = json.loads(data)
            if category in self.knowledge_base:
                self.knowledge_base[category].append(entry)
                return f"✅ Saved to {category}"
            else:
                return f"❌ Unknown category: {category}"
        except Exception as e:
            return f"❌ Error saving: {e}"
    
    # ============ Orchestration Logic ============
    
    async def run_turn(self, agent: Agent, messages: List[Dict]) -> Response:
        """
        Execute one turn with an agent (may involve tool calls and handoffs)
        
        Args:
            agent: Current agent
            messages: Conversation history
            
        Returns:
            Response with final agent and new messages
        """
        current_agent = agent
        num_init_messages = len(messages)
        messages = messages.copy()
        
        # Convert tools to function schemas
        tool_schemas = []
        tools_map = {}
        
        for tool in current_agent.tools:
            schema = self._function_to_schema(tool)
            tool_schemas.append(schema)
            tools_map[tool.__name__] = tool
        
        max_iterations = 10  # Prevent infinite loops
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            
            # Call model with current agent's context
            if tool_schemas:
                response = await self.client.chat_with_tools(
                    messages=[{"role": "system", "content": current_agent.instructions}] + messages,
                    tools=tool_schemas
                )
                
                # Extract from dict response
                content = response.get("content")
                tool_calls_data = response.get("tool_calls", [])
                
                # Reconstruct tool calls in expected format
                tool_calls = []
                for tc_data in tool_calls_data:
                    from types import SimpleNamespace
                    tc = SimpleNamespace(
                        id=tc_data["id"],
                        function=SimpleNamespace(
                            name=tc_data["function"]["name"],
                            arguments=json.dumps(tc_data["function"]["arguments"])
                        )
                    )
                    tool_calls.append(tc)
            else:
                # No tools, use simple chat
                response_obj = await self.client.chat(
                    messages=[{"role": "system", "content": current_agent.instructions}] + messages
                )
                content = response_obj.choices[0].message.content
                tool_calls = []
            
            # Add message to conversation
            messages.append({
                "role": "assistant",
                "content": content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    } for tc in tool_calls
                ]
            })
            
            # Print agent response
            if content:
                print(f"\n🤖 {current_agent.name}: {content}")
            
            # Check for tool calls
            if not tool_calls:
                break
            
            # Execute tool calls
            for tool_call in tool_calls:
                func_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                
                print(f"🔧 {current_agent.name}: {func_name}({args})")
                
                # Execute function
                if func_name in tools_map:
                    func_result = tools_map[func_name](**args)
                    # Await if coroutine
                    if asyncio.iscoroutine(func_result):
                        result = await func_result
                    else:
                        result = func_result
                else:
                    result = f"Unknown tool: {func_name}"
                
                # Check if result is an Agent (handoff)
                if isinstance(result, Agent):
                    current_agent = result
                    result_str = f"Transferred to {current_agent.name}. Adopt persona immediately."
                    
                    # Update tools for new agent
                    tool_schemas = []
                    tools_map = {}
                    for tool in current_agent.tools:
                        schema = self._function_to_schema(tool)
                        tool_schemas.append(schema)
                        tools_map[tool.__name__] = tool
                else:
                    result_str = str(result)
                
                # Add tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_str
                })
        
        return Response(
            agent=current_agent,
            messages=messages[num_init_messages:],
            metadata={"iterations": iteration}
        )
    
    def _function_to_schema(self, func: Callable) -> Dict:
        """Convert Python function to OpenAI tool schema"""
        import inspect
        
        type_map = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object",
            type(None): "null",
        }
        
        sig = inspect.signature(func)
        parameters = {}
        required = []
        
        for param_name, param in sig.parameters.items():
            param_type = type_map.get(param.annotation, "string")
            parameters[param_name] = {"type": param_type}
            
            if param.default == inspect.Parameter.empty:
                required.append(param_name)
        
        return {
            "type": "function",
            "function": {
                "name": func.__name__,
                "description": (func.__doc__ or "").strip(),
                "parameters": {
                    "type": "object",
                    "properties": parameters,
                    "required": required,
                },
            },
        }
    
    async def run_conversation(self, initial_message: str):
        """
        Run a full multi-agent conversation
        
        Args:
            initial_message: User's initial message
        """
        print("\n" + "="*70)
        print("🚀 MULTI-AGENT SLURM SYSTEM")
        print("="*70)
        print("\nAgents available:")
        print("  1. Chat Agent - Friendly Q&A interface")
        print("  2. Terminal Agent - Direct command execution (squeue, sinfo, etc.)")
        print("  3. Slurm Planning Agent - Complex job script generation")
        print("  4. Execution Agent - Validation & script execution")
        print("  5. ReAct Agent - Complex reasoning (debug, troubleshoot, workflows)")
        print(f"\n📋 Session: {self.ctx.context.session_id}")
        print("="*70 + "\n")
        
        # Set initial agent in context
        self.ctx.context.current_agent = "Chat Agent"
        
        # Start with chat agent
        current_agent = self.chat_agent
        messages = [{"role": "user", "content": initial_message}]
        
        print(f"👤 User: {initial_message}")
        
        # Store user interaction (both legacy and context)
        self.knowledge_base["user_interactions"].append({
            "request": initial_message,
            "timestamp": "now"
        })
        
        # Run conversation loop
        max_turns = 20
        for turn in range(max_turns):
            response = await self.run_turn(current_agent, messages)
            current_agent = response.agent
            messages.extend(response.messages)
            
            # Check if conversation should end
            if not any(msg.get("tool_calls") for msg in response.messages):
                break
        
        print("\n" + "="*70)
        print("✅ CONVERSATION COMPLETE")
        print("="*70)
        
        # Show context summary
        summary = self.ctx.context.get_summary()
        print(f"\n📊 Session Summary:")
        print(f"   • Handoffs: {len(summary['handoff_chain'])}")
        print(f"   • Commands run: {summary['commands_run']}")
        print(f"   • Scripts generated: {summary['scripts_generated']}")
        if summary['errors']:
            print(f"   • Errors: {summary['errors']}")
        if self.ctx.context.handoff_chain:
            print(f"   • Flow: {' → '.join(self.ctx.context.handoff_chain)}")
        
        return messages
    
    def get_context(self) -> AgentContext:
        """Get the current run context for external access"""
        return self.ctx.context


# ============ Demo ============

async def demo():
    """Demo showcasing all agents"""
    print("\n" + "="*70)
    print("MULTI-AGENT SYSTEM DEMO")
    print("="*70)
    
    orchestrator = MultiAgentOrchestrator()
    
    # Test cases showing when Chat Agent transfers to different agents
    test_messages = [
        # Should go to Terminal Agent (direct execution)
        "show my jobs",
        
        # Should go to ReAct Agent (complex reasoning)
        # "why might my GPU job be stuck in pending?",
    ]
    
    for msg in test_messages:
        print(f"\n{'='*70}")
        print(f"TEST: {msg}")
        print('='*70)
        
        await orchestrator.run_conversation(msg)
        
        print()


async def demo_terminal_only():
    """Demo terminal agent direct execution"""
    print("\n" + "="*70)
    print("TERMINAL AGENT DIRECT DEMO")
    print("="*70)
    
    orchestrator = MultiAgentOrchestrator()
    
    # Direct terminal commands
    test_inputs = [
        "show my jobs",
        "check cluster status", 
        "show details for job 12345",
    ]
    
    for user_input in test_inputs:
        print(f"\n👤 User: {user_input}")
        result = await orchestrator.execute_terminal_command(user_input)
        print(f"📤 Result:\n{result}")
    
    # Show context accumulated
    print("\n" + "-"*40)
    print("📊 Context accumulated:")
    ctx = orchestrator.get_context()
    print(f"   Terminal outputs: {len(ctx.terminal_outputs)}")
    print(f"   Explanations: {len(ctx.explanations)}")
    
    print("\n" + "="*70)
    print("TERMINAL DEMO COMPLETE")
    print("="*70)


async def demo_react_only():
    """Demo ReAct agent reasoning"""
    print("\n" + "="*70)
    print("REACT AGENT REASONING DEMO")
    print("="*70)
    
    orchestrator = MultiAgentOrchestrator()
    
    # Complex reasoning goals
    goal = "Help me understand why a GPU job might fail and set up a proper job script with validation"
    
    print(f"\n👤 Goal: {goal}")
    result = await orchestrator.run_react_reasoning(goal)
    print(f"\n📤 Result:\n{result}")
    
    print("\n" + "="*70)
    print("REACT DEMO COMPLETE")
    print("="*70)


async def demo_context():
    """Demo showing context accumulation across agents"""
    print("\n" + "="*70)
    print("CONTEXT API DEMO (OpenAI SDK Pattern)")
    print("="*70)
    
    orchestrator = MultiAgentOrchestrator(user_id="demo_user")
    
    print(f"\n📋 Session: {orchestrator.ctx.context.session_id}")
    print(f"👤 User: {orchestrator.ctx.context.user_id}")
    
    # Run multiple commands to accumulate context
    commands = [
        "show my jobs",
        "check cluster status",
        "what is GRES?",
    ]
    
    for cmd in commands:
        print(f"\n{'─'*40}")
        print(f"👤 {cmd}")
        result = await orchestrator.execute_terminal_command(cmd)
        print(f"📤 {result[:200]}...")
    
    # Show accumulated context
    print("\n" + "="*70)
    print("📊 ACCUMULATED CONTEXT")
    print("="*70)
    
    ctx = orchestrator.get_context()
    
    print(f"\n📋 Session: {ctx.session_id}")
    print(f"👤 User: {ctx.user_id}")
    print(f"\n🖥️  Terminal Outputs ({len(ctx.terminal_outputs)}):")
    for out in ctx.terminal_outputs:
        print(f"   • {out['command']} → {'✅' if out['success'] else '❌'}")
    
    print(f"\n💡 Explanations ({len(ctx.explanations)}):")
    for exp in ctx.explanations:
        print(f"   • {exp['topic'][:50]}...")
    
    print(f"\n🔄 Handoff Chain: {ctx.handoff_chain}")
    print(f"\n📊 Summary: {ctx.get_summary()}")


async def demo_confirmation():
    """Demo showing two-level confirmation system"""
    print("\n" + "="*70)
    print("CONFIRMATION SYSTEM DEMO")
    print("="*70)
    print("\nTwo types of confirmation:")
    print("  1. Chat confirmation - Before agent handoffs (optional)")
    print("  2. Tool confirmation - Before dangerous commands (required)")
    print("="*70)
    
    # Create orchestrator with interactive confirmation
    orchestrator = MultiAgentOrchestrator(
        user_id="demo_user",
        confirmation_mode="interactive",  # Will ask for confirmation
        confirm_handoffs=False,  # Don't confirm handoffs (keep it fast)
        confirm_dangerous=True   # Confirm dangerous commands
    )
    
    print(f"\n📋 Session: {orchestrator.ctx.context.session_id}")
    print(f"⚙️  Mode: {orchestrator.confirmation.mode}")
    print(f"   Confirm handoffs: {orchestrator.confirmation.confirm_handoffs}")
    print(f"   Confirm dangerous: {orchestrator.confirmation.confirm_dangerous}")
    
    # Test dangerous command (should trigger confirmation)
    test_commands = [
        ("Safe command", "show my jobs"),
        ("Safe command", "check cluster status"),
        ("Dangerous command", "cancel job 12345"),  # scancel - should prompt
    ]
    
    for label, cmd in test_commands:
        print(f"\n{'─'*40}")
        print(f"📌 {label}")
        print(f"👤 User: {cmd}")
        result = await orchestrator.execute_terminal_command(cmd)
        print(f"📤 Result:\n{result[:300]}...")
    
    print("\n" + "="*70)
    print("CONFIRMATION DEMO COMPLETE")
    print("="*70)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        if mode == "--terminal":
            asyncio.run(demo_terminal_only())
        elif mode == "--react":
            asyncio.run(demo_react_only())
        elif mode == "--context":
            asyncio.run(demo_context())
        elif mode == "--confirm":
            asyncio.run(demo_confirmation())
        elif mode == "--conversation":
            if len(sys.argv) > 2:
                msg = " ".join(sys.argv[2:])
                asyncio.run(MultiAgentOrchestrator().run_conversation(msg))
            else:
                asyncio.run(MultiAgentOrchestrator().run_conversation("show my jobs"))
        else:
            print("Usage:")
            print("  python multi_agent_system.py              # Run full demo")
            print("  python multi_agent_system.py --terminal   # Terminal agent demo")
            print("  python multi_agent_system.py --react      # ReAct agent demo")
            print("  python multi_agent_system.py --context    # Context API demo")
            print("  python multi_agent_system.py --confirm    # Confirmation system demo")
            print("  python multi_agent_system.py --conversation 'message'  # Custom conversation")
    else:
        asyncio.run(demo())