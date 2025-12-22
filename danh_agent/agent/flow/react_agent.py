"""
Single ReAct Agent - Works Like Claude

Architecture (same as how Claude works):
┌─────────────────────────────────────────────┐
│  Each Call = Full Context                   │
│  ┌─────────────────────────────────────┐    │
│  │ System Prompt                       │    │
│  │ + Conversation History              │    │
│  │ + Action History (tool results)     │    │
│  │ + Current User Message              │    │
│  └─────────────────────────────────────┘    │
│              ↓                              │
│         ONE inference                       │
│              ↓                              │
│      Action OR Final Answer                 │
│              ↓                              │
│    (If action) → Execute → Loop back        │
│    (If answer) → Return to user             │
│    (If dangerous) → Ask confirmation        │
└─────────────────────────────────────────────┘

Key differences from multi-agent:
- NO handoffs - single agent handles everything
- NO separate reasoning agent - reasoning is inline
- System manages the loop, not the agent
- Full context preserved in each call
"""
import logging
from typing import Optional, AsyncGenerator, Dict, Any, List, Union
import json

from agents import Agent, Runner
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from agents.model_settings import ModelSettings
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from typing import Literal

from flow.slurm_actions import (
    SlurmActionExecutor,
    SlurmActionUnion,  # All actions (analysis + job management)
    is_dangerous,
    get_danger_reason,
)
from utils.slurm_tools_minimal import SlurmConnection

logger = logging.getLogger(__name__)


# ============ Model Configuration ============
def create_ollama_model(model_name: str = "qwen3-coder:latest") -> OpenAIChatCompletionsModel:
    """Create Ollama-compatible model."""
    client = AsyncOpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
    return OpenAIChatCompletionsModel(model=model_name, openai_client=client)


# ============ ReAct Decision Schema ============

class ReActDecision(BaseModel):
    """
    Single decision output - either an action OR a final answer.
    
    The agent outputs ONE of:
    1. action + null answer → Execute and loop
    2. null action + answer → Done, return to user  
    3. action (dangerous) + null answer → Ask confirmation
    """
    model_config = {"extra": "forbid"}
    
    # Thinking trace (always present)
    thought: str = Field(
        description="Your reasoning about what to do next. Be specific."
    )
    
    # Action to execute (null if giving final answer)
    action: Optional[SlurmActionUnion] = Field(
        default=None,
        description="Action to execute. Set to null if you have the final answer."
    )
    
    # Final answer (null if need to execute action first)
    final_answer: Optional[str] = Field(
        default=None,
        description="Your final answer to the user. Only set when you have enough information."
    )
    
    # Confidence that we have enough info (0-1)
    confidence: float = Field(
        default=0.5,
        description="How confident you are (0-1). If < 0.7 and no final_answer, suggest an action."
    )


# ============ System Prompt ============

REACT_SYSTEM_PROMPT = """You are a Slurm cluster assistant. You help users with job management and cluster analysis.

## How You Work (ReAct Pattern)
1. THINK: Analyze what the user needs and what you know so far
2. DECIDE: Either execute an action OR give a final answer
3. OBSERVE: If you executed an action, you'll see the results
4. REPEAT: Until you can confidently answer

## Available Actions (Analysis - Safe, auto-execute)
- run_analysis: General cluster analysis (analysis_id: analyze_my_jobs, analyze_failed_jobs, analyze_pending_jobs, analyze_cluster_status, analyze_gpu_resources)
- squeue: Query current job queue (filter by job_id, user, state)
- sacct: Query job history (filter by job_id, user, state like FAILED/TIMEOUT/COMPLETED)
- sinfo: Query node/partition status (filter by state: idle/alloc/down/drain/mix)
- sprio: Query job priorities
- scontrol_show_job: Detailed info for ONE specific job (requires job_id)
- scontrol_show_node: Detailed node info
- scontrol_show_partition: Partition configuration
- sshare: Fairshare information
- sdiag: Scheduler diagnostics

## Available Actions (Job Management - Some need confirmation)
- sbatch: Submit a batch job (script_content or script_path required)
- srun: Run interactive command
- scancel: Cancel a job (DANGEROUS - requires confirmation, needs job_id)
- scontrol_hold: Hold a job (DANGEROUS, needs job_id)
- scontrol_release: Release a held job (needs job_id)
- scontrol_requeue: Requeue a job (DANGEROUS, needs job_id)
- scontrol_update_job: Modify job parameters (DANGEROUS, needs job_id and updates)

## Rules
1. Start with run_analysis for general questions
2. Use sacct with specific job_id when you see failed job IDs in output
3. NEVER repeat the same action twice - check what was already done
4. If you see job IDs in output, investigate them specifically
5. Give final_answer when you have enough info to help the user
6. Be concise in final answers

## Parameter Rules
- Only use values you SEE in outputs or user message
- Never invent job IDs, usernames, or other values
- Leave parameters null if not specified
"""


# ============ Single ReAct Agent System ============

class SlurmReActAgent:
    """
    Single ReAct agent - works like Claude.
    
    System manages the loop:
    1. Build context (history + observations)
    2. Call agent once
    3. If action → execute → add to observations → loop
    4. If final_answer → return to user
    5. If dangerous action → ask confirmation
    """
    
    MAX_ITERATIONS = 5  # Prevent infinite loops
    
    def __init__(
        self,
        model: str = "qwen3-coder:latest",
        base_url: str = "http://localhost:11434/v1",
        connection: Optional[SlurmConnection] = None
    ):
        self.model_name = model
        self.base_url = base_url
        self._connection = connection
        self._executor: Optional[SlurmActionExecutor] = None
        
        # Create model
        self.sdk_model = create_ollama_model(model)
        
        # Single agent with ReAct output
        self.agent = Agent(
            name="Slurm Assistant",
            instructions=REACT_SYSTEM_PROMPT,
            model=self.sdk_model,
            model_settings=ModelSettings(temperature=0.1),
            output_type=ReActDecision,
        )
    
    async def _ensure_connection(self) -> SlurmConnection:
        """Ensure MCP connection is established."""
        if self._connection is None:
            self._connection = SlurmConnection()
        if not self._connection.connected:
            await self._connection.connect()
        return self._connection
    
    async def _get_executor(self) -> SlurmActionExecutor:
        """Get or create executor."""
        if self._executor is None:
            conn = await self._ensure_connection()
            self._executor = SlurmActionExecutor(conn)
        return self._executor
    
    def _build_context(
        self,
        user_message: str,
        conversation_history: List[Dict[str, str]],
        action_history: List[Dict[str, Any]]
    ) -> str:
        """
        Build full context for the agent - like how Claude receives context.
        
        Context = Conversation History + Action History + Current Message
        """
        parts = []
        
        # Recent conversation history (last 4 exchanges)
        if conversation_history:
            recent = conversation_history[-8:]  # Last 4 user+assistant pairs
            if recent:
                parts.append("## Recent Conversation")
                for msg in recent:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")[:500]
                    if content:
                        parts.append(f"{role}: {content}")
                parts.append("")
        
        # Action history from this investigation (the key part!)
        if action_history:
            parts.append("## Actions Taken So Far (DO NOT REPEAT)")
            for i, entry in enumerate(action_history, 1):
                action_type = entry.get("action", "unknown")
                params = entry.get("params", {})
                output = entry.get("output", "")
                
                # Truncate output for context
                if len(output) > 1500:
                    output = output[:1500] + "... (truncated)"
                
                parts.append(f"### Step {i}: {action_type}")
                if params:
                    parts.append(f"Parameters: {json.dumps(params)}")
                parts.append(f"Output:\n```\n{output}\n```")
                parts.append("")
        
        # Current user message
        parts.append(f"## Current User Request\n{user_message}")
        
        return "\n".join(parts)
    
    async def run_streaming(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Run ReAct loop with streaming updates.
        
        This is the main loop - system manages iterations, not the agent.
        """
        conversation_history = conversation_history or []
        action_history: List[Dict[str, Any]] = []
        
        try:
            await self._ensure_connection()
            executor = await self._get_executor()
            
            yield {"type": "status", "message": "Thinking..."}
            
            for iteration in range(1, self.MAX_ITERATIONS + 1):
                # Build full context (like Claude gets)
                context = self._build_context(
                    user_message, 
                    conversation_history, 
                    action_history
                )
                
                # Single agent call
                result = await Runner.run(
                    starting_agent=self.agent,
                    input=context
                )
                
                decision = result.final_output
                
                # DEBUG: Log what we got
                logger.info(f"Decision type: {type(decision)}")
                if isinstance(decision, ReActDecision):
                    logger.info(f"Decision - thought: {decision.thought[:100] if decision.thought else 'None'}")
                    logger.info(f"Decision - action: {decision.action}")
                    logger.info(f"Decision - final_answer: {decision.final_answer[:100] if decision.final_answer else 'None'}")
                else:
                    logger.info(f"Raw decision: {decision}")
                
                # Validate decision type
                if not isinstance(decision, ReActDecision):
                    yield {
                        "type": "error",
                        "message": f"Unexpected output type: {type(decision)}"
                    }
                    break
                
                # === THINKING ===
                yield {
                    "type": "thinking",
                    "step": iteration,
                    "thought": decision.thought,
                    "confidence": decision.confidence
                }
                
                # === FINAL ANSWER ===
                if decision.final_answer:
                    yield {
                        "type": "final_answer",
                        "message": decision.final_answer,
                        "steps_taken": len(action_history)
                    }
                    yield {"type": "done"}
                    return
                
                # === NO ACTION AND NO ANSWER ===
                if not decision.action:
                    yield {
                        "type": "final_answer",
                        "message": decision.thought,  # Use thought as answer
                        "steps_taken": len(action_history)
                    }
                    yield {"type": "done"}
                    return
                
                # === DANGEROUS ACTION - NEED CONFIRMATION ===
                action_type = decision.action.action
                if is_dangerous(decision.action):  # Pass the action object, not string
                    yield {
                        "type": "confirm_required",
                        "message": f"⚠️ {get_danger_reason(decision.action)}",
                        "action": decision.action.model_dump(),
                        "thought": decision.thought
                    }
                    return  # Wait for user confirmation
                
                # === EXECUTE SAFE ACTION ===
                params = {k: v for k, v in decision.action.model_dump().items() 
                         if v is not None and k != 'action'}
                
                yield {
                    "type": "acting",
                    "step": iteration,
                    "action": action_type,
                    "parameters": params
                }
                
                # Execute
                exec_result = await executor.execute_action(decision.action)
                
                # Get output for display and history
                result_data = exec_result.get("result", {})
                if isinstance(result_data, dict) and "output" in result_data:
                    output_text = result_data["output"]
                else:
                    output_text = json.dumps(result_data, indent=2)
                
                # Add to action history (this is the key - accumulating context)
                action_history.append({
                    "action": action_type,
                    "params": params,
                    "output": output_text,
                    "success": exec_result.get("success", False)
                })
                
                # === EXECUTION RESULT ===
                yield {
                    "type": "execution_result",
                    "step": iteration,
                    "action": action_type,
                    "success": exec_result.get("success", False),
                    "output": output_text
                }
                
                # Check for repeated action (safeguard)
                if len(action_history) >= 2:
                    last = action_history[-1]
                    prev = action_history[-2]
                    if last["action"] == prev["action"] and last["params"] == prev["params"]:
                        yield {
                            "type": "warning",
                            "message": "Detected repeated action, stopping to prevent loop"
                        }
                        yield {
                            "type": "final_answer",
                            "message": f"Based on the investigation so far: {decision.thought}",
                            "steps_taken": len(action_history)
                        }
                        yield {"type": "done"}
                        return
            
            # Max iterations reached
            yield {
                "type": "final_answer",
                "message": f"Investigation completed after {self.MAX_ITERATIONS} steps. Here's what I found based on the data collected.",
                "steps_taken": len(action_history)
            }
            yield {"type": "done"}
            
        except Exception as e:
            logger.error(f"ReAct error: {e}")
            import traceback
            traceback.print_exc()
            yield {"type": "error", "message": str(e)}
    
    async def execute_confirmed_action(
        self,
        action_dict: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a previously confirmed dangerous action."""
        try:
            executor = await self._get_executor()
            return await executor.execute_action_from_dict(action_dict)
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def disconnect(self):
        """Clean up connections."""
        if self._connection and self._connection.connected:
            await self._connection.disconnect()
    
    async def __aenter__(self):
        await self._ensure_connection()
        return self
    
    async def __aexit__(self, *args):
        await self.disconnect()


# ============ Convenience Functions ============

async def run_react_streaming(
    message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None
) -> AsyncGenerator[Dict[str, Any], None]:
    """Quick one-shot streaming execution."""
    agent = SlurmReActAgent()
    try:
        async for event in agent.run_streaming(message, conversation_history):
            yield event
    finally:
        await agent.disconnect()
