"""
FastAPI Server for Slurm Agent with OpenAI SDK
Clean, simple API for cluster management
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn
import json
import logging
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager

from flow.slurm_agent import SlurmAgent
from flow.slurm_structured_agent import SlurmStructuredAgent

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global agents
agent = None
structured_agent = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle management"""
    global agent, structured_agent
    try:
        # Initialize traditional tool-calling agent
        agent = SlurmAgent(
            model="qwen2.5:7b",
            temperature=0.0,
            max_iterations=10,
            parallel_tool_calls=True
        )
        logger.info(f"Tool-calling agent initialized: {agent.client.model}")
        
        # Initialize structured output agent
        structured_agent = SlurmStructuredAgent(
            model="qwen2.5:7b",
            temperature=0.0
        )
        logger.info(f"Structured agent initialized: {structured_agent.client.model}")
        
    except Exception as e:
        logger.error(f"Failed to initialize agents: {e}")
        raise
    
    yield
    
    logger.info("Shutting down agents")
    if structured_agent and structured_agent.connection.connected:
        await structured_agent.connection.disconnect()


app = FastAPI(
    title="Slurm Agent API",
    description="AI agent for Slurm cluster management using OpenAI SDK",
    version="2.0.0",
    lifespan=lifespan
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    stream: bool = False


class ChatResponse(BaseModel):
    success: bool
    content: str
    tool_calls: List[Dict[str, Any]] = []


@app.get("/")
async def root():
    return {
        "message": "Slurm Agent API",
        "version": "2.0.0",
        "framework": "OpenAI SDK + Ollama",
        "status": "running"
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "agent_ready": agent is not None
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Chat with the Slurm agent
    
    Send messages to interact with Slurm cluster.
    The agent will use tools as needed.
    """
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages provided")
    
    try:
        # Convert Pydantic models to dicts
        messages = [msg.model_dump() for msg in request.messages]
        
        # Execute agent
        result = await agent.chat(messages)
        
        return ChatResponse(
            success=result.get("success", True),
            content=result.get("content", ""),
            tool_calls=result.get("tool_calls", [])
        )
        
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/simple")
async def simple_chat(message: str):
    """
    Simple single-message interaction
    
    Quick way to send a single request without conversation history
    """
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    
    try:
        result = await agent.run(message)
        
        return {
            "success": result.get("success", True),
            "content": result.get("content", ""),
            "tool_calls": result.get("tool_calls", [])
        }
        
    except Exception as e:
        logger.error(f"Simple chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/stream")
async def stream_chat(request: ChatRequest):
    """
    Streaming chat response
    
    Returns Server-Sent Events with incremental updates
    """
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    
    async def generate():
        try:
            messages = [msg.model_dump() for msg in request.messages]
            
            # Send status
            yield f"data: {json.dumps({'type': 'status', 'content': 'Processing request...'})}\n\n"
            
            # Execute agent
            result = await agent.chat(messages)
            
            # Stream tool calls
            if result.get("tool_calls"):
                for tool_call in result["tool_calls"]:
                    yield f"data: {json.dumps({'type': 'tool', 'content': tool_call})}\n\n"
            
            # Stream final response
            yield f"data: {json.dumps({'type': 'response', 'content': result.get('content', ''), 'done': True})}\n\n"
            
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream"
    )


@app.get("/tools")
async def list_tools():
    """List available Slurm tools"""
    from utils.slurm_tools import SLURM_TOOLS
    
    return {
        "tools": [
            {
                "name": tool["function"]["name"],
                "description": tool["function"]["description"]
            }
            for tool in SLURM_TOOLS
        ]
    }


@app.post("/execute_tool")
async def execute_tool_direct(tool_name: str, arguments: Dict[str, Any]):
    """
    Direct tool execution without agent
    
    Useful for testing or direct Slurm commands
    """
    try:
        from utils.slurm_tools import execute_tool
        
        result = await execute_tool(tool_name, arguments)
        
        return {
            "success": True,
            "tool": tool_name,
            "result": json.loads(result) if isinstance(result, str) else result
        }
        
    except Exception as e:
        logger.error(f"Tool execution error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/structured")
async def chat_structured(request: ChatRequest):
    """
    Chat with structured Pydantic output
    
    Example: Get job information in a structured format
    """
    try:
        from pydantic import BaseModel
        
        # Define structure for job info
        class JobSummary(BaseModel):
            total_jobs: int
            running: int
            pending: int
            summary: str
        
        result = await agent.client.chat_structured(
            messages=[{"role": "system", "content": agent.SYSTEM_PROMPT}] + 
                     [{"role": m.role, "content": m.content} for m in request.messages],
            response_format=JobSummary
        )
        
        return {
            "success": True,
            "structured_output": result.model_dump(),
            "type": "JobSummary"
        }
        
    except Exception as e:
        logger.error(f"Structured chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/parallel")
async def chat_parallel_tools(request: ChatRequest):
    """
    Chat with parallel tool calls enabled
    
    Can execute multiple Slurm commands simultaneously
    """
    try:
        from utils.slurm_tools import SLURM_TOOLS
        
        result = await agent.client.chat_with_tools(
            messages=[{"role": "system", "content": agent.SYSTEM_PROMPT}] + 
                     [{"role": m.role, "content": m.content} for m in request.messages],
            tools=SLURM_TOOLS,
            parallel_tool_calls=True
        )
        
        return {
            "success": True,
            "content": result["content"],
            "tool_calls": result["tool_calls"],
            "usage": result["usage"],
            "parallel": True
        }
        
    except Exception as e:
        logger.error(f"Parallel chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/logprobs")
async def chat_with_logprobs(request: ChatRequest, top_n: int = 5):
    """
    Chat with log probabilities
    
    Returns token-level probabilities for debugging/analysis
    """
    try:
        result = await agent.client.chat_with_logprobs(
            messages=[{"role": "system", "content": agent.SYSTEM_PROMPT}] + 
                     [{"role": m.role, "content": m.content} for m in request.messages],
            top_logprobs=top_n
        )
        
        return {
            "success": True,
            "content": result["content"],
            "logprobs": result["logprobs"],
            "usage": result["usage"]
        }
        
    except Exception as e:
        logger.error(f"Logprobs chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/features")
async def list_features():
    """
    List all enhanced OpenAI API features available
    """
    return {
        "features": {
            "structured_outputs": {
                "description": "Pydantic model-based structured responses",
                "endpoint": "/chat/structured"
            },
            "structured_agent": {
                "description": "Agent generates Slurm command sequences as structured JSON",
                "endpoints": {
                    "plan": "/slurm/plan",
                    "execute": "/slurm/execute",
                    "approve": "/slurm/approve"
                }
            },
            "parallel_tool_calls": {
                "description": "Execute multiple Slurm commands simultaneously",
                "endpoint": "/chat/parallel"
            },
            "streaming": {
                "description": "Stream responses with delta accumulation",
                "endpoint": "/stream"
            },
            "logprobs": {
                "description": "Token-level log probabilities",
                "endpoint": "/chat/logprobs"
            },
            "tool_choice": {
                "description": "Control tool calling behavior (auto/required/none/specific)",
                "note": "Use tool_choice parameter in chat requests"
            },
            "advanced_params": {
                "description": "Temperature, top_p, frequency_penalty, presence_penalty, seed",
                "note": "Configure via agent initialization"
            },
            "usage_tracking": {
                "description": "Detailed token usage statistics",
                "note": "Included in all tool call responses"
            }
        },
        "client_version": "2.0.0",
        "agents": {
            "tool_calling": agent.client.model if agent else None,
            "structured": structured_agent.client.model if structured_agent else None
        }
    }


# ===== STRUCTURED AGENT ENDPOINTS =====

class SlurmPlanRequest(BaseModel):
    message: str
    conversation_history: Optional[List[ChatMessage]] = None


class SlurmExecuteRequest(BaseModel):
    message: str
    conversation_history: Optional[List[ChatMessage]] = None


class SlurmApproveRequest(BaseModel):
    sequence: Dict[str, Any]  # SlurmCommandSequence as dict


@app.post("/slurm/plan")
async def plan_slurm_commands(request: SlurmPlanRequest):
    """
    Generate Slurm command sequence without execution
    
    Returns structured plan for review/approval
    """
    if not structured_agent:
        raise HTTPException(status_code=503, detail="Structured agent not initialized")
    
    try:
        history = [msg.model_dump() for msg in request.conversation_history] if request.conversation_history else None
        
        result = await structured_agent.plan_only(
            user_message=request.message,
            conversation_history=history
        )
        
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error", "Plan generation failed"))
        
        return {
            "success": True,
            "sequence": result["sequence"],
            "plan_message": result.get("final_message", ""),
            "note": "Review the plan and use /slurm/approve to execute"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Plan generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/slurm/execute")
async def execute_slurm_commands(request: SlurmExecuteRequest):
    """
    Generate and execute Slurm command sequence
    
    One-shot: plan generation + execution
    """
    if not structured_agent:
        raise HTTPException(status_code=503, detail="Structured agent not initialized")
    
    try:
        history = [msg.model_dump() for msg in request.conversation_history] if request.conversation_history else None
        
        result = await structured_agent.run(
            user_message=request.message,
            conversation_history=history,
            execute=True
        )
        
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error", "Execution failed"))
        
        return {
            "success": True,
            "sequence": result["sequence"],
            "executed": result.get("executed", False),
            "execution_summary": result.get("execution_summary", {}),
            "execution_results": result.get("execution_results", []),
            "message": result.get("final_message", "")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Execution error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/slurm/approve")
async def approve_and_execute(request: SlurmApproveRequest):
    """
    Execute a previously generated command sequence
    
    Use this after reviewing plan from /slurm/plan
    """
    if not structured_agent:
        raise HTTPException(status_code=503, detail="Structured agent not initialized")
    
    try:
        # Import here to avoid circular import
        from utils.slurm_commands import SlurmCommandSequence
        
        # Parse sequence from dict
        sequence = SlurmCommandSequence(**request.sequence)
        
        result = await structured_agent.execute_sequence(sequence)
        
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error", "Execution failed"))
        
        return {
            "success": True,
            "execution_summary": result.get("execution_summary", {}),
            "execution_results": result.get("execution_results", []),
            "message": result.get("final_message", "")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Approve and execute error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=20000,
        reload=True,
        log_level="info"
    )
