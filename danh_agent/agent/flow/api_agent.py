"""
Agentic System with API-based Confirmation

This module provides an API layer for UI integration:
- Async confirmation requests
- WebSocket support for real-time updates
- REST API endpoints for step control
- Event-driven architecture for UI updates
"""
import asyncio
from typing import List, Dict, Any, Optional, Callable, Awaitable
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime
import json
import uuid


# ============ API Models ============

class StepStatus(str, Enum):
    PENDING = "pending"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ConfirmationRequest(BaseModel):
    """Request sent to UI for confirmation"""
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    step_number: int
    thought: str
    action: str
    action_input: str
    context: Dict[str, Any] = {}
    timestamp: datetime = Field(default_factory=datetime.now)
    timeout_seconds: int = 300  # 5 minute default timeout


class ConfirmationResponse(BaseModel):
    """Response from UI"""
    request_id: str
    confirmed: bool
    user_message: Optional[str] = None  # Optional user feedback
    modified_input: Optional[str] = None  # User can modify action input
    timestamp: datetime = Field(default_factory=datetime.now)


class AgentStep(BaseModel):
    """A single step in agent execution"""
    step_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    step_number: int
    status: StepStatus = StepStatus.PENDING
    thought: str = ""
    action: str = ""
    action_input: str = ""
    observation: str = ""
    confirmation_request: Optional[ConfirmationRequest] = None
    confirmation_response: Optional[ConfirmationResponse] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


class AgentSession(BaseModel):
    """Complete agent session state"""
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    goal: str
    status: str = "active"  # active, paused, completed, failed
    steps: List[AgentStep] = []
    current_step: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    context: Dict[str, Any] = {}


class AgentEvent(BaseModel):
    """Event for UI updates (WebSocket)"""
    event_type: str  # step_started, confirmation_required, step_completed, etc.
    session_id: str
    step_id: Optional[str] = None
    data: Dict[str, Any] = {}
    timestamp: datetime = Field(default_factory=datetime.now)


# ============ Confirmation Manager ============

class ConfirmationManager:
    """
    Manages confirmation requests and responses
    
    Supports multiple confirmation modes:
    - callback: Call a function for confirmation
    - queue: Use asyncio queue for async confirmation
    - auto: Auto-confirm all (for testing)
    - manual: Wait for explicit API call
    """
    
    def __init__(self, mode: str = "auto"):
        self.mode = mode
        self.pending_requests: Dict[str, ConfirmationRequest] = {}
        self.responses: Dict[str, ConfirmationResponse] = {}
        
        # For queue-based confirmation
        self._request_queue: asyncio.Queue = asyncio.Queue()
        self._response_futures: Dict[str, asyncio.Future] = {}
        
        # For callback-based confirmation
        self._confirmation_callback: Optional[Callable[[ConfirmationRequest], Awaitable[ConfirmationResponse]]] = None
        
        # Event listeners for UI updates
        self._event_listeners: List[Callable[[AgentEvent], Awaitable[None]]] = []
    
    def set_callback(self, callback: Callable[[ConfirmationRequest], Awaitable[ConfirmationResponse]]):
        """Set callback function for confirmations"""
        self._confirmation_callback = callback
        self.mode = "callback"
    
    def add_event_listener(self, listener: Callable[[AgentEvent], Awaitable[None]]):
        """Add listener for agent events (for WebSocket broadcast)"""
        self._event_listeners.append(listener)
    
    async def emit_event(self, event: AgentEvent):
        """Emit event to all listeners"""
        for listener in self._event_listeners:
            try:
                await listener(event)
            except Exception as e:
                print(f"Event listener error: {e}")
    
    async def request_confirmation(
        self,
        step_number: int,
        thought: str,
        action: str,
        action_input: str,
        session_id: str = "",
        context: Dict[str, Any] = None
    ) -> ConfirmationResponse:
        """
        Request confirmation for an action
        
        Returns ConfirmationResponse with user's decision
        """
        request = ConfirmationRequest(
            step_number=step_number,
            thought=thought,
            action=action,
            action_input=action_input,
            context=context or {}
        )
        
        self.pending_requests[request.request_id] = request
        
        # Emit event for UI
        await self.emit_event(AgentEvent(
            event_type="confirmation_required",
            session_id=session_id,
            data={
                "request_id": request.request_id,
                "step_number": step_number,
                "thought": thought,
                "action": action,
                "action_input": action_input[:500]
            }
        ))
        
        # Handle based on mode
        if self.mode == "auto":
            # Auto-confirm for testing
            response = ConfirmationResponse(
                request_id=request.request_id,
                confirmed=True
            )
            
        elif self.mode == "callback" and self._confirmation_callback:
            # Use callback
            response = await self._confirmation_callback(request)
            
        elif self.mode == "queue":
            # Put request in queue and wait for response
            await self._request_queue.put(request)
            
            # Create future for response
            future = asyncio.get_event_loop().create_future()
            self._response_futures[request.request_id] = future
            
            # Wait for response (with timeout)
            try:
                response = await asyncio.wait_for(
                    future,
                    timeout=request.timeout_seconds
                )
            except asyncio.TimeoutError:
                response = ConfirmationResponse(
                    request_id=request.request_id,
                    confirmed=False,
                    user_message="Confirmation timeout"
                )
                
        elif self.mode == "manual":
            # Wait for manual API call
            future = asyncio.get_event_loop().create_future()
            self._response_futures[request.request_id] = future
            
            try:
                response = await asyncio.wait_for(
                    future,
                    timeout=request.timeout_seconds
                )
            except asyncio.TimeoutError:
                response = ConfirmationResponse(
                    request_id=request.request_id,
                    confirmed=False,
                    user_message="Confirmation timeout"
                )
        else:
            # Default: auto-confirm
            response = ConfirmationResponse(
                request_id=request.request_id,
                confirmed=True
            )
        
        # Store response
        self.responses[request.request_id] = response
        del self.pending_requests[request.request_id]
        
        return response
    
    def submit_response(self, response: ConfirmationResponse):
        """
        Submit a confirmation response (called by API/UI)
        """
        if response.request_id in self._response_futures:
            future = self._response_futures[response.request_id]
            if not future.done():
                future.set_result(response)
            del self._response_futures[response.request_id]
    
    def get_pending_requests(self) -> List[ConfirmationRequest]:
        """Get all pending confirmation requests"""
        return list(self.pending_requests.values())
    
    def get_next_pending(self) -> Optional[ConfirmationRequest]:
        """Get the next pending request (FIFO)"""
        if self.pending_requests:
            return list(self.pending_requests.values())[0]
        return None


# ============ API-Ready Agentic System ============

class APIAgenticSystem:
    """
    Agentic system with API support for UI integration
    
    Features:
    - Session management
    - Step-by-step execution with confirmation
    - Event emission for real-time UI updates
    - REST API compatible interface
    """
    
    def __init__(
        self,
        model: str = "qwen3-coder:latest",
        confirmation_mode: str = "auto"
    ):
        self.model = model
        self.confirmation_manager = ConfirmationManager(mode=confirmation_mode)
        
        # Session storage
        self.sessions: Dict[str, AgentSession] = {}
        
        # Initialize LLM client
        import sys
        sys.path.insert(0, '/mnt/e/workspace/uni/specialized_project/danh_agent/agent')
        from utils.openai_client import OllamaClient
        self.client = OllamaClient(model=model)
    
    # ============ Session Management ============
    
    def create_session(self, goal: str) -> AgentSession:
        """Create a new agent session"""
        session = AgentSession(goal=goal)
        self.sessions[session.session_id] = session
        return session
    
    def get_session(self, session_id: str) -> Optional[AgentSession]:
        """Get session by ID"""
        return self.sessions.get(session_id)
    
    def list_sessions(self) -> List[AgentSession]:
        """List all sessions"""
        return list(self.sessions.values())
    
    # ============ Step Execution ============
    
    async def think(self, session: AgentSession, observation: str) -> Dict[str, str]:
        """Generate next action using ReAct reasoning"""
        # Build context from previous steps
        history = "\n".join([
            f"Step {s.step_number}: {s.action} → {s.observation[:100]}..."
            for s in session.steps[-5:] if s.observation
        ])
        
        prompt = f"""You are an AI agent working towards a goal.

GOAL: {session.goal}

PREVIOUS STEPS:
{history if history else "None yet"}

CURRENT OBSERVATION:
{observation}

Available actions:
- explain: Explain a Slurm concept
- generate_commands: Create Slurm commands
- validate: Validate generated commands
- execute: Save/execute commands
- review: Review work done
- complete: Mark goal achieved

Respond in JSON:
{{
    "thought": "Your reasoning",
    "action": "action_name",
    "action_input": "input for action"
}}"""

        response = await self.client.chat(
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        
        return json.loads(response.choices[0].message.content)
    
    async def execute_action(self, action: str, action_input: str, session: AgentSession) -> str:
        """Execute an action and return observation"""
        if action == "explain":
            response = await self.client.chat(
                messages=[
                    {"role": "system", "content": "You are a Slurm expert. Be concise."},
                    {"role": "user", "content": f"Explain: {action_input}"}
                ]
            )
            return response.choices[0].message.content
            
        elif action == "generate_commands":
            from flow.slurm_structured_agent import SlurmStructuredAgent
            from utils.slurm_commands import SlurmCommandSequence, SlurmCommandBuilder
            
            agent = SlurmStructuredAgent(model=self.model)
            result = await agent.plan_only(action_input)
            
            sequence = SlurmCommandSequence(**result["sequence"])
            builder = SlurmCommandBuilder()
            script = builder.compile_to_shell(sequence)
            
            # Store in session context
            if "scripts" not in session.context:
                session.context["scripts"] = []
            session.context["scripts"].append(script)
            
            return f"Generated {len(sequence.commands)} commands:\n{script[:500]}..."
            
        elif action == "validate":
            if not session.context.get("scripts"):
                return "No scripts to validate"
            
            script = session.context["scripts"][-1]
            response = await self.client.chat(
                messages=[
                    {"role": "system", "content": "Validate this Slurm script briefly."},
                    {"role": "user", "content": script}
                ]
            )
            return response.choices[0].message.content
            
        elif action == "execute":
            if not session.context.get("scripts"):
                return "No scripts to save"
            
            script = session.context["scripts"][-1]
            path = f"/tmp/agent_{session.session_id[:8]}.sh"
            with open(path, 'w') as f:
                f.write(script)
            import os
            os.chmod(path, 0o755)
            return f"✅ Saved to: {path}"
            
        elif action == "review":
            return f"Session has {len(session.steps)} steps, {len(session.context.get('scripts', []))} scripts"
            
        elif action == "complete":
            session.status = "completed"
            return "GOAL_COMPLETED"
            
        else:
            return f"Unknown action: {action}"
    
    async def run_step(self, session: AgentSession) -> AgentStep:
        """
        Execute a single step with confirmation
        
        Returns the completed step
        """
        step_number = len(session.steps) + 1
        step = AgentStep(step_number=step_number)
        step.started_at = datetime.now()
        step.status = StepStatus.PENDING
        
        session.steps.append(step)
        session.current_step = step_number
        session.updated_at = datetime.now()
        
        # Emit step started event
        await self.confirmation_manager.emit_event(AgentEvent(
            event_type="step_started",
            session_id=session.session_id,
            step_id=step.step_id,
            data={"step_number": step_number}
        ))
        
        try:
            # Get last observation
            last_obs = session.steps[-2].observation if len(session.steps) > 1 else f"Starting: {session.goal}"
            
            # Think
            decision = await self.think(session, last_obs)
            step.thought = decision.get("thought", "")
            step.action = decision.get("action", "complete")
            step.action_input = decision.get("action_input", "")
            
            # Request confirmation
            step.status = StepStatus.AWAITING_CONFIRMATION
            
            response = await self.confirmation_manager.request_confirmation(
                step_number=step_number,
                thought=step.thought,
                action=step.action,
                action_input=step.action_input,
                session_id=session.session_id,
                context={"goal": session.goal}
            )
            
            step.confirmation_response = response
            
            if response.confirmed:
                step.status = StepStatus.CONFIRMED
                
                # Use modified input if provided
                action_input = response.modified_input or step.action_input
                
                # Execute
                step.status = StepStatus.EXECUTING
                step.observation = await self.execute_action(step.action, action_input, session)
                step.status = StepStatus.COMPLETED
                
            else:
                step.status = StepStatus.REJECTED
                step.observation = f"User rejected: {response.user_message or 'No reason given'}"
            
        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = str(e)
            step.observation = f"Error: {e}"
        
        step.completed_at = datetime.now()
        session.updated_at = datetime.now()
        
        # Emit step completed event
        await self.confirmation_manager.emit_event(AgentEvent(
            event_type="step_completed",
            session_id=session.session_id,
            step_id=step.step_id,
            data={
                "status": step.status.value,
                "action": step.action,
                "observation": step.observation[:200]
            }
        ))
        
        return step
    
    async def run_session(
        self,
        session: AgentSession,
        max_steps: int = 10
    ) -> AgentSession:
        """
        Run a complete session with step-by-step execution
        """
        await self.confirmation_manager.emit_event(AgentEvent(
            event_type="session_started",
            session_id=session.session_id,
            data={"goal": session.goal, "max_steps": max_steps}
        ))
        
        for i in range(max_steps):
            if session.status != "active":
                break
            
            step = await self.run_step(session)
            
            # Check for completion
            if step.observation == "GOAL_COMPLETED":
                session.status = "completed"
                break
            
            # Check for failures
            if step.status == StepStatus.FAILED:
                # Could implement retry logic here
                pass
        
        await self.confirmation_manager.emit_event(AgentEvent(
            event_type="session_completed",
            session_id=session.session_id,
            data={"status": session.status, "steps": len(session.steps)}
        ))
        
        return session


# ============ FastAPI Router (for integration) ============

def create_api_router(system: APIAgenticSystem):
    """
    Create FastAPI router for the agentic system
    
    Usage:
        from fastapi import FastAPI
        app = FastAPI()
        system = APIAgenticSystem()
        app.include_router(create_api_router(system), prefix="/agent")
    """
    from fastapi import APIRouter, HTTPException, WebSocket
    from fastapi.responses import JSONResponse
    
    router = APIRouter()
    
    @router.post("/sessions")
    async def create_session(goal: str):
        """Create a new agent session"""
        session = system.create_session(goal)
        return session.model_dump()
    
    @router.get("/sessions")
    async def list_sessions():
        """List all sessions"""
        return [s.model_dump() for s in system.list_sessions()]
    
    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str):
        """Get session details"""
        session = system.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session.model_dump()
    
    @router.post("/sessions/{session_id}/run")
    async def run_session(session_id: str, max_steps: int = 10):
        """Run a session (async)"""
        session = system.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        result = await system.run_session(session, max_steps)
        return result.model_dump()
    
    @router.post("/sessions/{session_id}/step")
    async def run_single_step(session_id: str):
        """Execute a single step"""
        session = system.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        step = await system.run_step(session)
        return step.model_dump()
    
    @router.get("/confirmations/pending")
    async def get_pending_confirmations():
        """Get all pending confirmation requests"""
        return [r.model_dump() for r in system.confirmation_manager.get_pending_requests()]
    
    @router.post("/confirmations/{request_id}/respond")
    async def respond_to_confirmation(request_id: str, confirmed: bool, user_message: str = None, modified_input: str = None):
        """Submit confirmation response"""
        response = ConfirmationResponse(
            request_id=request_id,
            confirmed=confirmed,
            user_message=user_message,
            modified_input=modified_input
        )
        system.confirmation_manager.submit_response(response)
        return {"status": "ok"}
    
    @router.websocket("/ws/{session_id}")
    async def websocket_endpoint(websocket: WebSocket, session_id: str):
        """WebSocket for real-time updates"""
        await websocket.accept()
        
        async def send_event(event: AgentEvent):
            if event.session_id == session_id:
                await websocket.send_json(event.model_dump())
        
        system.confirmation_manager.add_event_listener(send_event)
        
        try:
            while True:
                data = await websocket.receive_text()
                # Handle incoming messages (e.g., confirmations)
                msg = json.loads(data)
                if msg.get("type") == "confirm":
                    response = ConfirmationResponse(
                        request_id=msg["request_id"],
                        confirmed=msg.get("confirmed", True),
                        user_message=msg.get("message"),
                        modified_input=msg.get("modified_input")
                    )
                    system.confirmation_manager.submit_response(response)
        except Exception:
            pass
    
    return router


# ============ Demo ============

async def demo_api_system():
    """Demo the API-based agentic system"""
    print("\n" + "="*60)
    print("🔌 API-BASED AGENTIC SYSTEM DEMO")
    print("="*60)
    
    # Create system with auto-confirm for demo
    system = APIAgenticSystem(
        model="qwen3-coder:latest",
        confirmation_mode="auto"
    )
    
    # Add event listener to see events
    async def print_event(event: AgentEvent):
        print(f"\n📡 EVENT: {event.event_type}")
        print(f"   Data: {json.dumps(event.data, default=str)[:100]}...")
    
    system.confirmation_manager.add_event_listener(print_event)
    
    # Create session
    goal = "Create a GPU job script with 4 GPUs and save it"
    print(f"\n🎯 Goal: {goal}")
    
    session = system.create_session(goal)
    print(f"\n📋 Session created: {session.session_id}")
    
    # Run session
    print("\n⚡ Running session...\n")
    result = await system.run_session(session, max_steps=5)
    
    # Summary
    print("\n" + "="*60)
    print("📊 SESSION SUMMARY")
    print("="*60)
    print(f"Status: {result.status}")
    print(f"Steps completed: {len(result.steps)}")
    
    for step in result.steps:
        status_icon = "✅" if step.status == StepStatus.COMPLETED else "❌"
        print(f"\n{status_icon} Step {step.step_number}: {step.action}")
        print(f"   Thought: {step.thought[:80]}...")
        print(f"   Result: {step.observation[:80]}...")


if __name__ == "__main__":
    asyncio.run(demo_api_system())
