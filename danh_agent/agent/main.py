"""
FastAPI Server for Slurm Agent with OpenAI SDK
Clean, simple API for cluster management

Uses structured output (output_type) approach for reliable execution.
Supports OpenWebUI streaming format for chat integration.
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn
import json
import logging
import uuid
import time
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager

from flow.slurm_structured_agent import SlurmStructuredAgent

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ===== OpenWebUI-compatible Streaming Helpers =====
def create_stream_chunk(
    model: str = "slurm-agent",
    content: Optional[str] = None,
    reasoning_content: Optional[str] = None,
    tool_calls: Optional[list] = None,
    finish_reason: Optional[str] = None,
) -> str:
    """
    Create an SSE-formatted streaming chunk compatible with OpenWebUI.
    
    Args:
        model: Model name for the chunk
        content: Main response content (appears in chat)
        reasoning_content: Thinking/reasoning content (appears in thinking dropdown)
        tool_calls: List of tool calls being made
        finish_reason: Set to "stop" for final chunk
    
    Returns:
        SSE-formatted string ready to yield
    """
    chunk = {
        "id": f"{model}-{str(uuid.uuid4())}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "logprobs": None,
            "finish_reason": finish_reason,
            "delta": {}
        }]
    }
    
    if content:
        chunk["choices"][0]["delta"]["content"] = content
    
    if reasoning_content:
        chunk["choices"][0]["delta"]["reasoning_content"] = reasoning_content
    
    if tool_calls:
        chunk["choices"][0]["delta"]["tool_calls"] = tool_calls
    
    return f"data: {json.dumps(chunk)}\n\n"


# ===== Session Management =====
# Session-based agents - one per session to prevent state mixing
_session_agents: Dict[str, tuple] = {}
_pending_confirmations: Dict[str, Dict[str, Any]] = {}  # session_id -> decision_data
SESSION_TIMEOUT = 3600  # 1 hour timeout for idle sessions


def get_agent(session_id: str = "default") -> SlurmStructuredAgent:
    """
    Get or create an agent for a specific session.
    Uses structured output approach for reliable execution.
    """
    global _session_agents
    
    current_time = time.time()
    
    # Clean up expired sessions
    expired = [k for k, (_, last_time) in _session_agents.items() 
               if current_time - last_time > SESSION_TIMEOUT]
    for k in expired:
        logger.info(f"Cleaning up expired session: {k}")
        del _session_agents[k]
    
    # Get or create agent for this session
    if session_id in _session_agents:
        agent_instance, _ = _session_agents[session_id]
        _session_agents[session_id] = (agent_instance, current_time)
        return agent_instance
    
    # Create new agent for this session
    logger.info(f"Creating new agent for session: {session_id}")
    agent_instance = SlurmStructuredAgent(model="qwen3-coder:latest")
    _session_agents[session_id] = (agent_instance, current_time)
    return agent_instance


# ===== App Lifecycle =====
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle management"""
    logger.info("🚀 Starting Slurm Agent API...")
    logger.info("Using structured output (output_type) approach")
    yield
    
    # Cleanup all sessions
    logger.info("Shutting down - cleaning up sessions...")
    for session_id, (agent, _) in _session_agents.items():
        try:
            await agent.disconnect()
        except Exception as e:
            logger.error(f"Error disconnecting session {session_id}: {e}")
    logger.info("Shutdown complete")


app = FastAPI(
    title="Slurm Agent API",
    description="AI agent for Slurm cluster management using structured output",
    version="3.0.0",
    lifespan=lifespan
)


# ===== Request/Response Models =====
class ChatMessage(BaseModel):
    role: str
    content: Optional[str] = None
    tool_calls: Optional[list] = None
    images: Optional[list] = None
    task: Optional[str] = "chat"


class ChatRequest(BaseModel):
    model: Optional[str] = "slurm-agent"
    messages: List[ChatMessage]
    stream: bool = True
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    model_config = {"extra": "allow"}


class ChatResponse(BaseModel):
    success: bool
    content: str
    tool_calls: List[Dict[str, Any]] = []


# ===== Basic Endpoints =====
@app.get("/")
async def root():
    return {
        "message": "Slurm Agent API",
        "version": "3.0.0",
        "framework": "OpenAI SDK + Ollama (Structured Output)",
        "status": "running",
        "active_sessions": len(_session_agents)
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "active_sessions": len(_session_agents)
    }


# ===== OpenWebUI-compatible Streaming Chat =====
@app.post("/v1/chat/completions")
async def openwebui_chat(request: ChatRequest):
    """
    OpenWebUI-compatible chat endpoint with streaming.
    
    Uses the OpenAI API format expected by OpenWebUI.
    Session isolation: Each session_id gets its own agent instance.
    """
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages provided")
    
    # Get session-based agent
    session_id = request.session_id or "default"
    user_id = request.user_id or "default"
    agent = get_agent(session_id)
    logger.info(f"📍 Session: {session_id}, User: {user_id}, Stream: {request.stream}")
    
    # Get last user message
    messages = [msg.model_dump() for msg in request.messages]
    
    user_message = ""
    message_task = "chat"
    for msg in reversed(messages):
        if msg.get("role") == "user" and msg.get("content"):
            user_message = msg["content"]
            message_task = msg.get("task", "chat")
            break
    
    # Handle non-streaming requests (follow-up generation, etc.)
    if not request.stream:
        logger.info(f"🔄 Non-streaming request (task: {message_task})")
        try:
            from utils.openai_client import OllamaClient
            client = OllamaClient(model="qwen3-coder:latest")
            
            response = await client.chat(messages=messages, temperature=0.7)
            content = response.choices[0].message.content if hasattr(response, 'choices') else str(response)
            
            # Return OpenAI-compatible JSON response
            return {
                "id": f"chatcmpl-{str(uuid.uuid4())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": request.model or "slurm-agent",
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content
                    },
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                }
            }
        except Exception as e:
            logger.error(f"Non-streaming chat error: {e}")
            return {
                "id": f"chatcmpl-{str(uuid.uuid4())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": request.model or "slurm-agent",
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": f"Error: {str(e)}"
                    },
                    "finish_reason": "stop"
                }]
            }
    
    # Streaming request handler
    async def generate_stream():
        try:
            if not user_message:
                yield create_stream_chunk(content="No message provided", finish_reason="stop")
                yield "data: [DONE]\n\n"
                return
                
            logger.info(f"📨 Message: {user_message[:100]}...")
            
            # Simple greetings bypass
            simple_greetings = ["hi", "hello", "hey", "thanks", "thank you", "bye", "goodbye", "ok", "okay"]
            is_simple_greeting = user_message.strip().lower() in simple_greetings
            
            # OpenWebUI generation tasks
            is_generation_task = (
                message_task in ["follow_up_generation", "title_generation", "tags_generation"] or
                any(task in user_message.lower() for task in ["### task:", "follow-up", "title", "tags generation"])
            )
            
            if is_simple_greeting or is_generation_task:
                task_type = "greeting" if is_simple_greeting else "generation task"
                logger.info(f"🎯 Using simple LLM for {task_type}")
                
                from utils.openai_client import OllamaClient
                client = OllamaClient(model="qwen3-coder:latest")
                
                if is_simple_greeting:
                    response = await client.chat(
                        messages=[
                            {"role": "system", "content": "You are a friendly Slurm assistant. Respond warmly."},
                            {"role": "user", "content": user_message}
                        ],
                        temperature=0.7
                    )
                else:
                    response = await client.chat(messages=messages, temperature=0.7)
                
                content = response.choices[0].message.content if hasattr(response, 'choices') else str(response)
                yield create_stream_chunk(content=content, finish_reason="stop")
                yield "data: [DONE]\n\n"
                return
            
            # Use structured agent with streaming + summarization
            logger.info("🔄 Starting agent streaming...")
            
            async for event in agent.run_streaming_with_summary(user_message, execute=True):
                event_type = event.get("type")
                
                if event_type == "thinking":
                    yield create_stream_chunk(
                        reasoning_content=f"🤔 {event.get('message', 'Processing...')}\n"
                    )
                
                elif event_type == "decision":
                    decision = event.get("decision", "")
                    message = event.get("message", "")
                    action_data = event.get("action", {})
                    reasoning = action_data.get("reasoning", "") if action_data else ""
                    
                    # Handle confirmation flow
                    if decision == "confirm":
                        # Store pending confirmation for this session
                        _pending_confirmations[session_id] = {
                            "action": action_data,
                            "timestamp": time.time()
                        }
                        # Show reasoning + confirmation message to user
                        if reasoning:
                            yield create_stream_chunk(
                                reasoning_content=f"💭 Reasoning: {reasoning}\n"
                            )
                        yield create_stream_chunk(
                            content=f"\n{message}\n",
                            finish_reason="stop"
                        )
                        yield "data: [DONE]\n\n"
                        return
                    
                    elif decision == "cancel":
                        # User declined, clear pending confirmation
                        _pending_confirmations.pop(session_id, None)
                        yield create_stream_chunk(
                            content=f"\n{message}\n",
                            finish_reason="stop"
                        )
                        yield "data: [DONE]\n\n"
                        return
                    
                    else:
                        # Show agent's reasoning transparently
                        if reasoning:
                            yield create_stream_chunk(
                                reasoning_content=f"💭 Reasoning: {reasoning}\n"
                            )
                        yield create_stream_chunk(
                            reasoning_content=f"📋 Decision: {decision}\n"
                        )
                
                elif event_type == "executing":
                    step = event.get("step", 0)
                    total = event.get("total", 1)
                    action = event.get("action", "")
                    reasoning = event.get("reasoning", "")
                    
                    # Show what action is being executed and why
                    if reasoning:
                        yield create_stream_chunk(
                            reasoning_content=f"⚡ Executing: {action}\n   💭 Why: {reasoning}\n"
                        )
                    else:
                        yield create_stream_chunk(
                            reasoning_content=f"⚡ Executing: {action}\n"
                        )
                
                elif event_type == "result":
                    status = "✓" if event.get("success") else "✗"
                    action = event.get("action", "")
                    output = event.get("output", "")
                    
                    # Show raw output in reasoning/thinking dropdown
                    yield create_stream_chunk(
                        reasoning_content=f"\n📊 Raw output ({action}):\n```\n{output}\n```\n"
                    )
                
                elif event_type == "summarizing":
                    yield create_stream_chunk(
                        reasoning_content=f"\n✨ {event.get('message', 'Generating summary...')}\n"
                    )
                
                elif event_type == "summary":
                    # Show summary as main content (visible to user)
                    summary = event.get("content", "")
                    command = event.get("command", "")
                    
                    content = f"\n{summary}\n"
                    yield create_stream_chunk(content=content)
                
                elif event_type == "done":
                    message = event.get("message", "Complete")
                    yield create_stream_chunk(
                        content=f"\n✅ {message}\n",
                        finish_reason="stop"
                    )
                    yield "data: [DONE]\n\n"
                
                elif event_type == "error":
                    yield create_stream_chunk(
                        content=f"\n❌ Error: {event.get('message', 'Unknown error')}\n",
                        finish_reason="stop"
                    )
                    yield "data: [DONE]\n\n"
            
            logger.info("✅ Streaming complete")
            
        except Exception as e:
            logger.error(f"Chat error: {e}")
            import traceback
            traceback.print_exc()
            yield create_stream_chunk(content=f"❌ Error: {str(e)}", finish_reason="stop")
            yield "data: [DONE]\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.get("/v1/models")
async def list_models():
    """OpenWebUI-compatible models endpoint."""
    return {
        "object": "list",
        "data": [
            {
                "id": "slurm-agent",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "slurm-agent",
                "name": "Slurm Agent",
                "description": "AI agent for Slurm cluster management with structured output"
            }
        ]
    }


# ===== Direct API Endpoints =====
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Non-streaming chat endpoint."""
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages provided")
    
    try:
        session_id = request.session_id or "default"
        agent = get_agent(session_id)
        
        # Get last user message
        user_message = ""
        for msg in reversed(request.messages):
            if msg.role == "user" and msg.content:
                user_message = msg.content
                break
        
        if not user_message:
            return ChatResponse(success=False, content="No message provided")
        
        result = await agent.run(user_message, execute=True)
        
        return ChatResponse(
            success=result.get("success", False),
            content=result.get("output", result.get("message", "")),
            tool_calls=[]
        )
        
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/slurm/execute")
async def execute_slurm(message: str, session_id: str = "default"):
    """
    Execute Slurm command directly.
    
    Args:
        message: Natural language request (e.g., "show my jobs")
        session_id: Session ID for agent isolation
    """
    try:
        agent = get_agent(session_id)
        result = await agent.run(message, execute=True)
        
        return {
            "success": result.get("success", False),
            "type": result.get("type"),
            "output": result.get("output", result.get("message", "")),
            "results": result.get("results", []),
            "executed": result.get("executed", False)
        }
        
    except Exception as e:
        logger.error(f"Execute error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/slurm/plan")
async def plan_slurm(message: str, session_id: str = "default"):
    """
    Generate Slurm command plan without executing.
    
    Args:
        message: Natural language request
        session_id: Session ID for agent isolation
    """
    try:
        agent = get_agent(session_id)
        result = await agent.plan_only(message)
        
        return {
            "success": result.get("success", False),
            "type": result.get("type"),
            "decision": result.get("decision"),
            "message": result.get("message", "")
        }
        
    except Exception as e:
        logger.error(f"Plan error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/slurm/stream")
async def stream_slurm(message: str, session_id: str = "default"):
    """
    Stream Slurm execution for real-time updates.
    """
    async def generate():
        try:
            agent = get_agent(session_id)
            
            async for event in agent.run_streaming(message, execute=True):
                yield f"data: {json.dumps(event)}\n\n"
                
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream"
    )


@app.get("/sessions")
async def list_sessions():
    """List active sessions."""
    return {
        "count": len(_session_agents),
        "sessions": [
            {
                "id": session_id,
                "age_seconds": int(time.time() - last_time)
            }
            for session_id, (_, last_time) in _session_agents.items()
        ]
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=20000,
        reload=True,
        log_level="info"
    )
