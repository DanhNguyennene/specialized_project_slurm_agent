"""FastAPI Server with OpenAI SDK Agent"""
from fastapi import FastAPI, HTTPException, Depends
from fastapi import status as fastapi_status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from datetime import datetime, timedelta

from pydantic import BaseModel
import uvicorn
import os
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from flow.agent_v2_openai import VMAgent, OLLAMA_MODEL, BASE_OLLAMA_URL, generate_vm_agent_streaming_completion
from utils.openai_adapter import create_ollama_client
from fastapi import Request

# Global agent instance
agent = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global agent
    try:
        # Initialize OpenAI client for local Ollama
        model = create_ollama_client(
            model=OLLAMA_MODEL,
            base_url=BASE_OLLAMA_URL,
            temperature=0.0
        )
        agent = VMAgent(model)
        print("Agent initialized successfully with OpenAI SDK")
    except Exception as e:
        print(f"Failed to initialize agent: {e}")
        raise
    
    yield
    
    # Shutdown
    print("Shutting down agent")

app = FastAPI(
    title="OpenAI SDK Agent API",
    description="An AI agent built with OpenAI SDK, MCP tools, and local Ollama",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/")
async def root():
    return {"message": "OpenAI SDK Agent API is running", "framework": "OpenAI SDK + Ollama"}

@app.get("/health", tags=["agent"])
async def health_check():
    return {"status": "healthy", "agent_ready": agent is not None}

class ChatResponse(BaseModel):
    model: str = "tma_agent_007"
    created_at: str
    message: Dict[str, Any]
    done_reason: Optional[str] = "stop"
    done: bool = True

class ChatRequest(BaseModel):
    stream: bool = False
import json
@app.post("/chat", tags=["agent"])
async def chat(request: Request):
    try:
        # Fix the JSON parsing issue
        body = await request.body()
        body_str = body.decode('utf-8')
        
        try:
            payload = json.loads(body_str)
            # If payload is a string, it's double-encoded
            if isinstance(payload, str):
                payload = json.loads(payload)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")
        
        stream = payload.get("stream", True)
        print(f"Received chat request with stream={stream}")

        if not agent:
            raise HTTPException(status_code=503, detail="Agent not initialized")
        
        messages = payload.get("messages", [])
        if not messages:
            raise HTTPException(status_code=400, detail="No messages provided")
        
        last_message = messages[-1]
        task = last_message.get("task", "chat")
        
        if task == "chat" and stream:
            return await generate_vm_agent_streaming_completion(
                user_input=messages, 
                thread_id=payload.get("thread_id", "default-agent")
            )
        else:
            # Non-streaming response
            response = await agent.generate_answer_exclusive(
                user_input=messages, 
                thread_id=payload.get("thread_id", "default-agent")
            )
            
            message_format = {
                "role": "assistant",
                "content": response['content'],
                "thinking": response.get("thinking", ""),
                "tool_calls": response.get("tool_calls", []),
                'task': task,
            }
            
            current_time = datetime.now(timezone.utc)
            created_at = current_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            
            return ChatResponse(
                model="tma_agent_007",
                created_at=created_at,
                message=message_format,
                done_reason="stop",
                done=True
            )

    except Exception as e:
        print(f"ERROR in chat endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


#region Authorization

#########################################################################
#                                                                       #
#       Authorize Admin for access to Database and server status        #
#                                                                       #
#########################################################################

SECRET_KEY = "your-secret-key"      # change in production
ALGORITHM = "HS256"                 # change in production
ACCESS_TOKEN_EXPIRE_MINUTES = 2.5   # admin access to update chroma database

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

class Token(BaseModel):
    access_token: str
    token_type: str

class User(BaseModel):
    username: str
    role: str  # e.g., "admin" or "user"

in_memory_users_db = {
    "adminuser": {
        "username": "adminuser",
        "password": "adminpass",  # In production, use hashed passwords
        "role": "admin"
    },
    "regularuser": {
        "username": "regularuser",
        "password": "userpass",
        "role": "user"
    }
}

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=fastapi_status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = in_memory_users_db.get(username)
    if user is None:
        raise credentials_exception
    return User(**user)

async def get_current_admin(current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(
            status_code=fastapi_status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    return current_user


# Token endpoint for login
@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = in_memory_users_db.get(form_data.username)
    if not user or user["password"] != form_data.password:
        raise HTTPException(
            status_code=fastapi_status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["username"]}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

#endregion


#region Main App run
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=20000,
        reload=True,
        log_level="info"
    )