"""
FastAPI Server for Slurm Agent with OpenAI SDK
Supports OpenWebUI streaming format for chat integration.
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import json
import logging
import uuid
import time
import os
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager

from flow.multi_agent import SlurmMultiAgentSystem

# Configuration
MCP_SERVER_URL = "http://localhost:3002"
CHARTS_DIR = "/tmp/slurm_charts"

# Ensure charts directory exists
os.makedirs(CHARTS_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ===== Streaming Helpers =====
def create_stream_chunk(
    content: Optional[str] = None,
    reasoning_content: Optional[str] = None,
    finish_reason: Optional[str] = None,
) -> str:
    """Create OpenWebUI-compatible SSE chunk."""
    chunk = {
        "id": f"slurm-{uuid.uuid4()}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "slurm-agent",
        "choices": [{
            "index": 0,
            "finish_reason": finish_reason,
            "delta": {}
        }]
    }
    if content:
        chunk["choices"][0]["delta"]["content"] = content
    if reasoning_content:
        chunk["choices"][0]["delta"]["reasoning_content"] = reasoning_content
    return f"data: {json.dumps(chunk)}\n\n"


# ===== Session Management =====
_session_agents: Dict[str, tuple] = {}
SESSION_TIMEOUT = 3600


def get_agent(session_id: str = "default") -> SlurmMultiAgentSystem:
    """Get or create agent for session."""
    global _session_agents
    current_time = time.time()
    
    # Clean expired sessions
    expired = [k for k, (_, t) in _session_agents.items() if current_time - t > SESSION_TIMEOUT]
    for k in expired:
        del _session_agents[k]
    
    if session_id in _session_agents:
        agent, _ = _session_agents[session_id]
        _session_agents[session_id] = (agent, current_time)
        return agent
    
    logger.info(f"Creating agent for session: {session_id}")
    agent = SlurmMultiAgentSystem(
        reasoning_model="gpt-oss:20b",
        tool_model="gpt-oss:20b",
        mcp_url=MCP_SERVER_URL,
        session_id=session_id
    )
    _session_agents[session_id] = (agent, current_time)
    return agent


# ===== App =====
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Slurm Agent API")
    yield
    for sid, (agent, _) in _session_agents.items():
        try:
            await agent.disconnect()
        except Exception as e:
            logger.error(f"Disconnect error {sid}: {e}")


app = FastAPI(title="Slurm Agent API", version="4.0.0", lifespan=lifespan)

# CORS for live dashboard iframe access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # OpenWebUI iframe needs access
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ===== Models =====
class ChatMessage(BaseModel):
    role: str
    content: Optional[str] = None
    task: Optional[str] = "chat"


class ChatRequest(BaseModel):
    model: Optional[str] = "slurm-agent"
    messages: List[ChatMessage]
    stream: bool = True
    session_id: Optional[str] = None
    chat_id: Optional[str] = None  # OpenWebUI's chat identifier
    user_id: Optional[str] = None
    model_config = {"extra": "allow"}


# ===== Endpoints =====
@app.get("/")
async def root():
    return {"status": "running", "sessions": len(_session_agents)}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/v1/models")
async def list_models():
    return {"object": "list", "data": [{"id": "slurm-agent", "object": "model"}]}


@app.post("/v1/chat/completions")
async def chat(request: ChatRequest):
    """OpenWebUI-compatible chat endpoint."""
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages")
    
    raw = request.model_dump()
    
    # Debug: log fields to understand what OpenWebUI sends
    logger.info(f"DEBUG raw request: chat_id={raw.get('chat_id')}, user_id={raw.get('user_id')}")
    
    # Extract session ID - chat_id is now forwarded from OpenWebUI metadata
    session_id = raw.get("chat_id") or raw.get("user_id")
    
    # If still no session ID, generate a unique one
    if not session_id:
        session_id = str(uuid.uuid4())
        logger.warning(f"No chat_id in request, generated new session: {session_id}")
    
    logger.info(f"Chat request - session_id: {session_id}")
    agent = get_agent(session_id)
    
    messages = [m.model_dump() for m in request.messages]
    user_message = ""
    task = "chat"
    for msg in reversed(messages):
        if msg.get("role") == "user" and msg.get("content"):
            user_message = msg["content"]
            task = msg.get("task", "chat")
            break
    
    # Non-streaming
    if not request.stream:
        try:
            from utils.openai_client import OllamaClient
            client = OllamaClient(model="qwen3-coder:latest")
            response = await client.chat(messages=messages, temperature=0.7)
            content = response.choices[0].message.content if hasattr(response, 'choices') else str(response)
            return {
                "id": f"chatcmpl-{uuid.uuid4()}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "slurm-agent",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]
            }
        except Exception as e:
            return {"choices": [{"message": {"content": f"Error: {e}"}, "finish_reason": "stop"}]}
    
    # Streaming
    async def stream():
        try:
            if not user_message:
                yield create_stream_chunk(content="No message", finish_reason="stop")
                yield "data: [DONE]\n\n"
                return
            
            # Generation tasks use simple LLM
            if task in ["follow_up_generation", "title_generation", "tags_generation"]:
                from utils.openai_client import OllamaClient
                client = OllamaClient(model="qwen3-coder:latest")
                response = await client.chat(messages=messages, temperature=0.7)
                content = response.choices[0].message.content if hasattr(response, 'choices') else str(response)
                yield create_stream_chunk(content=content, finish_reason="stop")
                yield "data: [DONE]\n\n"
                return
            
            # Agent streaming
            async for event in agent.run_streaming(user_message):
                t = event.get("type")
                if t == "status":
                    yield create_stream_chunk(reasoning_content=f"{event.get('message', '')}\n")
                elif t == "final_answer":
                    # Stream the full response including chart artifacts
                    # Charts are wrapped in markers for display but SDK history will include them
                    yield create_stream_chunk(content=event.get("message", ""))
                elif t == "error":
                    yield create_stream_chunk(content=f"Error: {event.get('message', '')}", finish_reason="stop")
                    yield "data: [DONE]\n\n"
                    return
                elif t == "done":
                    yield create_stream_chunk(finish_reason="stop")
                    yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield create_stream_chunk(content=f"Error: {e}", finish_reason="stop")
            yield "data: [DONE]\n\n"
    
    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/sessions")
async def list_sessions():
    return {"count": len(_session_agents), "sessions": list(_session_agents.keys())}


@app.delete("/sessions")
async def clear_all_sessions():
    """Clear all sessions and SQLite conversation history."""
    global _session_agents
    count = len(_session_agents)
    
    # Disconnect all agents
    for sid, (agent, _) in list(_session_agents.items()):
        try:
            await agent.disconnect()
        except Exception as e:
            logger.error(f"Disconnect error {sid}: {e}")
    
    _session_agents = {}
    
    # Also clear the SQLite conversation database
    import os
    db_files = [
        "/tmp/slurm_agent_conversations.db",
        "/tmp/slurm_pending_actions.db"
    ]
    for db in db_files:
        if os.path.exists(db):
            os.remove(db)
            logger.info(f"Removed {db}")
    
    return {"cleared": count, "message": "All sessions and conversation history cleared"}


@app.delete("/sessions/{session_id}")
async def clear_session(session_id: str):
    """Clear a specific session."""
    global _session_agents
    if session_id in _session_agents:
        agent, _ = _session_agents.pop(session_id)
        try:
            await agent.disconnect()
        except Exception:
            pass
        return {"cleared": session_id}
    return {"error": "Session not found"}


@app.get("/charts/{chart_filename}")
async def get_chart(chart_filename: str):
    """Serve generated chart images."""
    # Security: only allow .png files and no path traversal
    if not chart_filename.endswith('.png') or '/' in chart_filename or '\\' in chart_filename:
        raise HTTPException(status_code=400, detail="Invalid chart filename")
    
    chart_path = os.path.join(CHARTS_DIR, chart_filename)
    if not os.path.exists(chart_path):
        raise HTTPException(status_code=404, detail="Chart not found")
    
    return FileResponse(chart_path, media_type="image/png")


@app.get("/api/cluster/status")
async def cluster_status():
    """Proxy to MCP server's cluster status endpoint."""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{MCP_SERVER_URL}/api/cluster/status", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return await resp.json()
    except Exception as e:
        return {"error": str(e), "available": False}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=20000, reload=True)
