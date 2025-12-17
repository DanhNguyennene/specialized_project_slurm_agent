"""
Terminal-like Slurm Agent (Copilot-style)

This is a conversational agent that:
- Executes simple commands directly (squeue, sinfo, scancel, etc.)
- Only generates scripts for complex batch jobs
- Learns from command outputs
- Provides explanations when asked

Like VS Code Copilot - natural conversation with direct action!
"""
import asyncio
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field
from enum import Enum
import json
import subprocess
import shlex


class CommandType(str, Enum):
    """Type of command execution"""
    DIRECT = "direct"      # Run command immediately (squeue, sinfo, etc.)
    SCRIPT = "script"      # Generate script for batch jobs
    EXPLAIN = "explain"    # Just explain, no execution
    QUESTION = "question"  # Answer a question


class CommandIntent(BaseModel):
    """What the user wants to do"""
    intent_type: CommandType
    command: Optional[str] = None  # The actual command to run
    explanation: str = ""  # Explanation for user
    needs_confirmation: bool = False  # Dangerous commands need confirmation
    script_content: Optional[str] = None  # For batch scripts


class TerminalAgent:
    """
    Terminal-like agent for Slurm
    
    - Direct execution for simple commands
    - Script generation for complex jobs
    - Conversational Q&A
    """
    
    def __init__(
        self,
        model: str = "qwen3-coder:latest",
        simulate: bool = True,  # True = don't actually run commands
        auto_execute: bool = False  # Auto-execute without confirmation
    ):
        self.model = model
        self.simulate = simulate
        self.auto_execute = auto_execute
        
        # Command history for context
        self.history: List[Dict[str, Any]] = []
        
        # Initialize LLM
        import sys
        sys.path.insert(0, '/mnt/e/workspace/uni/specialized_project/danh_agent/agent')
        from utils.openai_client import OllamaClient
        self.client = OllamaClient(model=model)
        
        # Dangerous commands that need confirmation
        self.dangerous_commands = ['scancel', 'scontrol update', 'scontrol hold', 'scontrol release']
    
    async def understand_intent(self, user_input: str) -> CommandIntent:
        """
        Understand what the user wants to do
        
        Returns:
            CommandIntent with type, command, and explanation
        """
        # Build context from history
        history_context = ""
        if self.history:
            recent = self.history[-5:]
            history_context = "\n".join([
                f"User: {h['input']}\nResult: {h.get('output', 'N/A')[:100]}..."
                for h in recent
            ])
        
        prompt = f"""You are a Slurm terminal assistant. Understand what the user wants.

RECENT HISTORY:
{history_context if history_context else "No previous commands"}

USER INPUT: {user_input}

Determine the intent:
1. DIRECT - Simple Slurm command to run (squeue, sinfo, sacct, scontrol show, etc.)
2. SCRIPT - Needs a batch script (sbatch job submission)
3. EXPLAIN - User wants explanation without running anything
4. QUESTION - User is asking a question

For DIRECT commands, provide the exact command to run.
For SCRIPT, generate the sbatch script.
For EXPLAIN/QUESTION, provide helpful information.

IMPORTANT: 
- Use DIRECT for: squeue, sinfo, sacct, scancel, scontrol show, sprio, sshare
- Use SCRIPT only for: submitting new jobs with sbatch
- Commands like "check queue" = squeue (DIRECT)
- Commands like "show my jobs" = squeue -u $USER (DIRECT)

Respond in JSON:
{{
    "intent_type": "direct|script|explain|question",
    "command": "the exact slurm command" or null,
    "explanation": "brief explanation of what this does",
    "needs_confirmation": true/false,
    "script_content": "full sbatch script" or null
}}"""

        response = await self.client.chat(
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        
        data = json.loads(response.choices[0].message.content)
        
        return CommandIntent(
            intent_type=CommandType(data.get("intent_type", "explain")),
            command=data.get("command"),
            explanation=data.get("explanation", ""),
            needs_confirmation=data.get("needs_confirmation", False),
            script_content=data.get("script_content")
        )
    
    def execute_command(self, command: str) -> Dict[str, Any]:
        """
        Execute a Slurm command
        
        Returns:
            Dict with success, output, error
        """
        if self.simulate:
            # Simulate output for testing
            return self._simulate_command(command)
        
        try:
            result = subprocess.run(
                shlex.split(command),
                capture_output=True,
                text=True,
                timeout=30
            )
            
            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr if result.returncode != 0 else None,
                "command": command
            }
            
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "output": "",
                "error": "Command timed out",
                "command": command
            }
        except Exception as e:
            return {
                "success": False,
                "output": "",
                "error": str(e),
                "command": command
            }
    
    def _simulate_command(self, command: str) -> Dict[str, Any]:
        """Simulate command output for testing"""
        cmd_lower = command.lower()
        
        if 'squeue' in cmd_lower:
            output = """JOBID  PARTITION  NAME      USER    ST  TIME   NODES  NODELIST
12345  gpu        train     user1   R   2:30:00  1     gpu-node-01
12346  gpu        eval      user1   PD  0:00     1     (Priority)
12347  cpu        preproc   user2   R   0:15:00  2     cpu-[01-02]"""
        
        elif 'sinfo' in cmd_lower:
            output = """PARTITION  AVAIL  TIMELIMIT  NODES  STATE  NODELIST
gpu*       up     7-00:00:00  4      idle   gpu-[01-04]
gpu        up     7-00:00:00  2      mix    gpu-[05-06]
cpu        up     2-00:00:00  10     idle   cpu-[01-10]
debug      up     1:00:00     2      idle   debug-[01-02]"""
        
        elif 'sacct' in cmd_lower:
            output = """JobID      JobName   Partition  State      Elapsed   MaxRSS
12340      train     gpu        COMPLETED  4:30:00   32000M
12341      eval      gpu        FAILED     0:05:00   8000M
12342      preproc   cpu        COMPLETED  0:45:00   16000M"""
        
        elif 'scontrol show' in cmd_lower:
            output = """JobId=12345 JobName=train
   UserId=user1(1000) GroupId=users(100)
   Priority=100 Nice=0 Account=default
   JobState=RUNNING Reason=None
   RunTime=02:30:00 TimeLimit=08:00:00
   NumNodes=1 NumCPUs=8 NumTasks=1
   TRES=cpu=8,mem=32G,gres/gpu=4"""
        
        elif 'scancel' in cmd_lower:
            output = "Job cancelled successfully"
        
        elif 'sprio' in cmd_lower:
            output = """JOBID  PARTITION  PRIORITY  AGE  FAIRSHARE  JOBSIZE
12346  gpu        1000      100  500        400"""
        
        elif 'sshare' in cmd_lower:
            output = """Account       User  RawShares  NormShares  RawUsage  EffectvUsage  FairShare
default       user1  100        0.5000      50000     0.2500        0.8000
default       user2  100        0.5000      75000     0.3750        0.6000"""
        
        else:
            output = f"[Simulated] Command executed: {command}"
        
        return {
            "success": True,
            "output": output,
            "error": None,
            "command": command,
            "simulated": True
        }
    
    async def process(self, user_input: str, confirm_callback=None) -> Dict[str, Any]:
        """
        Process user input and execute if appropriate
        
        Args:
            user_input: What the user said
            confirm_callback: Optional async function to get confirmation
            
        Returns:
            Dict with response, command, output, etc.
        """
        # Understand intent
        intent = await self.understand_intent(user_input)
        
        result = {
            "input": user_input,
            "intent": intent.intent_type.value,
            "explanation": intent.explanation
        }
        
        if intent.intent_type == CommandType.DIRECT:
            # Direct command execution
            result["command"] = intent.command
            
            # Check if needs confirmation
            if intent.needs_confirmation and not self.auto_execute:
                if confirm_callback:
                    confirmed = await confirm_callback(
                        f"Execute: {intent.command}?\n{intent.explanation}"
                    )
                    if not confirmed:
                        result["status"] = "cancelled"
                        result["message"] = "Command cancelled by user"
                        return result
            
            # Execute
            exec_result = self.execute_command(intent.command)
            result.update(exec_result)
            result["status"] = "executed" if exec_result["success"] else "failed"
            
        elif intent.intent_type == CommandType.SCRIPT:
            # Script generation
            result["script"] = intent.script_content
            result["status"] = "script_generated"
            result["message"] = "Script generated. Use /save to save it or /run to submit."
            
        elif intent.intent_type in [CommandType.EXPLAIN, CommandType.QUESTION]:
            # Just explanation
            result["status"] = "answered"
            result["message"] = intent.explanation
        
        # Save to history
        self.history.append(result)
        
        return result
    
    async def chat_loop(self):
        """
        Interactive chat loop - like terminal
        """
        print("\n" + "="*60)
        print("🖥️  SLURM TERMINAL AGENT")
        print("="*60)
        print("\nCommands:")
        print("  /help     - Show help")
        print("  /history  - Show command history")
        print("  /clear    - Clear history")
        print("  /mode     - Toggle simulate/live mode")
        print("  /quit     - Exit")
        print("\nJust type naturally! e.g., 'show my jobs', 'check cluster status'")
        print("="*60 + "\n")
        
        while True:
            try:
                user_input = input("You: ").strip()
                
                if not user_input:
                    continue
                
                # Handle special commands
                if user_input.startswith('/'):
                    cmd = user_input.lower()
                    
                    if cmd == '/quit' or cmd == '/exit':
                        print("\n👋 Goodbye!")
                        break
                    
                    elif cmd == '/help':
                        print("\n📚 Examples:")
                        print("  • 'show my jobs' → squeue -u $USER")
                        print("  • 'check cluster status' → sinfo")
                        print("  • 'cancel job 12345' → scancel 12345")
                        print("  • 'show job 12345 details' → scontrol show job 12345")
                        print("  • 'submit a GPU training job' → generates sbatch script")
                        print("  • 'what is GRES?' → explains GRES")
                        continue
                    
                    elif cmd == '/history':
                        print("\n📜 Recent commands:")
                        for h in self.history[-10:]:
                            status = "✅" if h.get("success") else "❌"
                            print(f"  {status} {h.get('command', h.get('input', 'N/A'))}")
                        continue
                    
                    elif cmd == '/clear':
                        self.history = []
                        print("🗑️  History cleared")
                        continue
                    
                    elif cmd == '/mode':
                        self.simulate = not self.simulate
                        mode = "SIMULATE" if self.simulate else "LIVE"
                        print(f"🔄 Mode: {mode}")
                        continue
                    
                    else:
                        print(f"❓ Unknown command: {user_input}")
                        continue
                
                # Process natural language input
                print("\n🤔 Processing...")
                
                async def confirm(msg):
                    response = input(f"\n⚠️  {msg} (y/n): ").strip().lower()
                    return response == 'y'
                
                result = await self.process(user_input, confirm_callback=confirm)
                
                # Display result
                print()
                
                if result["status"] == "executed":
                    print(f"💻 Command: {result.get('command')}")
                    print(f"📝 {result['explanation']}")
                    print("\n" + "-"*40)
                    print(result.get("output", ""))
                    print("-"*40)
                    if result.get("simulated"):
                        print("(Simulated output)")
                
                elif result["status"] == "script_generated":
                    print(f"📝 {result['explanation']}")
                    print("\n" + "-"*40)
                    print(result.get("script", ""))
                    print("-"*40)
                    print("\n💡 Use '/save' to save or ask to submit")
                
                elif result["status"] == "answered":
                    print(f"💡 {result.get('message', result['explanation'])}")
                
                elif result["status"] == "cancelled":
                    print(f"⏹️  {result.get('message')}")
                
                elif result["status"] == "failed":
                    print(f"❌ Error: {result.get('error')}")
                
                print()
                
            except KeyboardInterrupt:
                print("\n\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"\n❌ Error: {e}\n")


# ============ FastAPI Integration ============

def create_terminal_router():
    """Create FastAPI router for terminal-like API"""
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel
    
    router = APIRouter(prefix="/terminal", tags=["Terminal"])
    
    # Shared agent instance
    agent = TerminalAgent(model="qwen3-coder:latest", simulate=True)
    
    class TerminalRequest(BaseModel):
        input: str
        auto_execute: bool = True
    
    class ConfirmRequest(BaseModel):
        command: str
        confirmed: bool
    
    @router.post("/execute")
    async def execute(request: TerminalRequest):
        """
        Execute a natural language Slurm request
        
        Examples:
        - "show my jobs"
        - "check cluster status"
        - "cancel job 12345"
        """
        agent.auto_execute = request.auto_execute
        result = await agent.process(request.input)
        return result
    
    @router.get("/history")
    async def get_history():
        """Get command history"""
        return {"history": agent.history[-20:]}
    
    @router.delete("/history")
    async def clear_history():
        """Clear command history"""
        agent.history = []
        return {"status": "cleared"}
    
    @router.post("/confirm")
    async def confirm_command(request: ConfirmRequest):
        """Confirm and execute a pending command"""
        if request.confirmed:
            result = agent.execute_command(request.command)
            agent.history.append(result)
            return result
        else:
            return {"status": "cancelled"}
    
    @router.get("/mode")
    async def get_mode():
        """Get current execution mode"""
        return {
            "simulate": agent.simulate,
            "auto_execute": agent.auto_execute
        }
    
    @router.post("/mode")
    async def set_mode(simulate: bool = True, auto_execute: bool = True):
        """Set execution mode"""
        agent.simulate = simulate
        agent.auto_execute = auto_execute
        return {
            "simulate": agent.simulate,
            "auto_execute": agent.auto_execute
        }
    
    return router


# ============ Demo ============

async def demo():
    """Quick demo of terminal agent"""
    print("\n" + "="*60)
    print("TERMINAL AGENT DEMO")
    print("="*60)
    
    agent = TerminalAgent(model="qwen3-coder:latest", simulate=True)
    
    test_inputs = [
        "show my jobs",
        "check cluster status",
        "show details for job 12345",
        "what is GRES?",
        "cancel job 12346"
    ]
    
    for user_input in test_inputs:
        print(f"\n👤 User: {user_input}")
        result = await agent.process(user_input)
        
        if result.get("command"):
            print(f"💻 Command: {result['command']}")
        print(f"📝 {result['explanation']}")
        
        if result.get("output"):
            print(f"\n{result['output'][:200]}...")
    
    print("\n" + "="*60)
    print("DEMO COMPLETE")
    print("="*60)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
        # Run interactive chat loop
        asyncio.run(TerminalAgent(
            model="qwen3-coder:latest",
            simulate=True
        ).chat_loop())
    else:
        # Run demo
        asyncio.run(demo())
