"""
Full Agentic System with ReAct Loop + Context Passing

Features:
1. Plan → Execute → Observe → Replan loop
2. Context passed between tasks
3. Interactive mode with user confirmation
4. Automatic replanning on failures
5. Knowledge base learning
6. Multiple specialized agents with handoffs
"""
import asyncio
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from enum import Enum
import json
import sys

sys.path.insert(0, '/mnt/e/workspace/uni/specialized_project/danh_agent/agent')

from utils.openai_client import OllamaClient
from utils.slurm_commands import SlurmCommandSequence, SlurmCommandBuilder


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"  
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_REPLAN = "needs_replan"


class Task(BaseModel):
    id: int
    title: str
    description: str
    agent: str
    status: TaskStatus = TaskStatus.PENDING
    dependencies: List[int] = []
    context: Dict[str, Any] = {}  # Context from previous tasks
    result: Optional[str] = None
    artifacts: Dict[str, Any] = {}  # Generated artifacts (scripts, etc)


class Plan(BaseModel):
    goal: str
    reasoning: str
    tasks: List[Task]
    iteration: int = 1


class ReActStep(BaseModel):
    """Single step in ReAct loop"""
    thought: str
    action: str
    action_input: str
    observation: str


class FullAgenticSystem:
    """
    Complete agentic system with:
    - Multi-agent orchestration
    - ReAct reasoning loop
    - Context passing between tasks
    - Iterative replanning
    - Knowledge accumulation
    """
    
    def __init__(self, model: str = "qwen3-coder:latest", interactive: bool = False):
        self.model = model
        self.interactive = interactive
        self.client = OllamaClient(model=model)
        
        # Execution context - passed between tasks
        self.execution_context = {
            "generated_scripts": [],
            "command_sequences": [],
            "explanations": [],
            "validations": [],
            "improvements": []
        }
        
        # Knowledge base
        self.knowledge = {
            "successful_plans": [],
            "failed_tasks": [],
            "user_preferences": []
        }
        
        # ReAct history
        self.react_history: List[ReActStep] = []
        
    async def think(self, observation: str, goal: str) -> Dict[str, str]:
        """
        ReAct thinking step - decide what to do next
        """
        history_context = ""
        if self.react_history:
            history_context = "\n".join([
                f"Step {i+1}: Thought: {s.thought} | Action: {s.action} | Observation: {s.observation[:100]}..."
                for i, s in enumerate(self.react_history[-5:])
            ])
        
        prompt = f"""You are an AI agent working towards a goal. Use ReAct reasoning.

GOAL: {goal}

PREVIOUS STEPS:
{history_context if history_context else "None yet"}

CURRENT OBSERVATION:
{observation}

Based on this, decide your next step.

Available actions:
- explain: Explain a Slurm concept to the user
- generate_commands: Create Slurm command sequences
- validate: Validate generated commands
- execute: Execute/save commands
- review: Review the work done so far
- complete: Mark the goal as achieved
- replan: Create a new plan if current approach isn't working

Respond in JSON:
{{
    "thought": "Your reasoning about what to do next",
    "action": "The action to take",
    "action_input": "Input for the action"
}}"""

        response = await self.client.chat(
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        
        return json.loads(response.choices[0].message.content)
    
    async def act(self, action: str, action_input: str) -> str:
        """
        Execute an action and return observation
        """
        if action == "explain":
            return await self._explain(action_input)
        elif action == "generate_commands":
            return await self._generate_commands(action_input)
        elif action == "validate":
            return await self._validate(action_input)
        elif action == "execute":
            return await self._execute(action_input)
        elif action == "review":
            return await self._review(action_input)
        elif action == "complete":
            return "GOAL_COMPLETED"
        elif action == "replan":
            return await self._replan(action_input)
        else:
            return f"Unknown action: {action}"
    
    async def _explain(self, topic: str) -> str:
        """Explain a Slurm concept"""
        response = await self.client.chat(
            messages=[
                {"role": "system", "content": "You are a helpful Slurm expert. Explain concepts clearly and concisely."},
                {"role": "user", "content": f"Explain: {topic}"}
            ]
        )
        explanation = response.choices[0].message.content
        self.execution_context["explanations"].append({
            "topic": topic,
            "content": explanation
        })
        return f"Explained: {topic}\n\n{explanation[:500]}..."
    
    async def _generate_commands(self, request: str) -> str:
        """Generate Slurm commands using structured output"""
        from flow.slurm_structured_agent import SlurmStructuredAgent
        
        agent = SlurmStructuredAgent(model=self.model)
        result = await agent.plan_only(request)
        
        sequence = SlurmCommandSequence(**result["sequence"])
        builder = SlurmCommandBuilder()
        script = builder.compile_to_shell(sequence)
        
        # Save to context
        self.execution_context["command_sequences"].append({
            "request": request,
            "sequence": result["sequence"],
            "script": script
        })
        self.execution_context["generated_scripts"].append(script)
        
        return f"Generated {len(sequence.commands)} commands:\n{sequence.description}\n\nScript preview:\n{script[:500]}..."
    
    async def _validate(self, what: str) -> str:
        """Validate generated commands/scripts"""
        # Get latest script
        if not self.execution_context["generated_scripts"]:
            return "No scripts to validate yet."
        
        latest_script = self.execution_context["generated_scripts"][-1]
        
        response = await self.client.chat(
            messages=[
                {"role": "system", "content": "You are a Slurm expert. Validate this script for correctness."},
                {"role": "user", "content": f"Validate this script:\n\n{latest_script}\n\nCheck for: {what}"}
            ]
        )
        
        validation = response.choices[0].message.content
        self.execution_context["validations"].append({
            "script": latest_script[:200],
            "validation": validation
        })
        
        return f"Validation result:\n{validation[:500]}..."
    
    async def _execute(self, what: str) -> str:
        """Execute/save commands"""
        if not self.execution_context["generated_scripts"]:
            return "No scripts to execute."
        
        latest_script = self.execution_context["generated_scripts"][-1]
        
        # Save script
        script_path = "/tmp/agentic_generated.sh"
        with open(script_path, 'w') as f:
            f.write(latest_script)
        
        import os
        os.chmod(script_path, 0o755)
        
        return f"✅ Script saved to: {script_path}\n\nTo run on Slurm: bash {script_path}\n\nScript content:\n{latest_script}"
    
    async def _review(self, aspect: str) -> str:
        """Review work done so far"""
        context_summary = f"""
Work done so far:
- Explanations: {len(self.execution_context['explanations'])}
- Command sequences: {len(self.execution_context['command_sequences'])}
- Scripts generated: {len(self.execution_context['generated_scripts'])}
- Validations: {len(self.execution_context['validations'])}
"""
        
        response = await self.client.chat(
            messages=[
                {"role": "system", "content": "You are a critical reviewer. Analyze the work and suggest improvements."},
                {"role": "user", "content": f"Review this work:\n{context_summary}\n\nFocus on: {aspect}"}
            ]
        )
        
        review = response.choices[0].message.content
        self.execution_context["improvements"].append(review)
        
        return f"Review:\n{review[:500]}..."
    
    async def _replan(self, reason: str) -> str:
        """Trigger replanning"""
        return f"NEEDS_REPLAN: {reason}"
    
    async def run_react_loop(self, goal: str, max_steps: int = 10) -> Dict[str, Any]:
        """
        Run the ReAct loop until goal is achieved or max steps reached
        """
        print("\n" + "🤖"*25)
        print("ReAct AGENTIC LOOP")
        print("🤖"*25)
        
        print(f"\n🎯 GOAL: {goal}\n")
        
        observation = f"Starting work on goal: {goal}"
        
        for step in range(1, max_steps + 1):
            print(f"\n{'─'*60}")
            print(f"STEP {step}/{max_steps}")
            print('─'*60)
            
            # Think
            print("\n🧠 Thinking...")
            decision = await self.think(observation, goal)
            
            thought = decision.get("thought", "")
            action = decision.get("action", "complete")
            action_input = decision.get("action_input", "")
            
            print(f"\n💭 Thought: {thought}")
            print(f"🎬 Action: {action}")
            print(f"📥 Input: {action_input[:100]}{'...' if len(action_input) > 100 else ''}")
            
            # Interactive confirmation
            if self.interactive:
                confirm = input("\nProceed? (y/n/q): ").strip().lower()
                if confirm == 'n':
                    observation = "User rejected action, waiting for new direction"
                    continue
                elif confirm == 'q':
                    break
            
            # Act
            print("\n⚡ Acting...")
            observation = await self.act(action, action_input)
            
            print(f"\n👁️ Observation: {observation[:300]}{'...' if len(observation) > 300 else ''}")
            
            # Record step
            self.react_history.append(ReActStep(
                thought=thought,
                action=action,
                action_input=action_input,
                observation=observation
            ))
            
            # Check for completion
            if observation == "GOAL_COMPLETED":
                print("\n✅ GOAL ACHIEVED!")
                break
            
            if "NEEDS_REPLAN" in observation:
                print("\n🔄 Replanning triggered...")
                # Could implement recursive replanning here
                
        # Summary
        print("\n" + "="*60)
        print("EXECUTION SUMMARY")
        print("="*60)
        
        print(f"\nSteps taken: {len(self.react_history)}")
        print(f"Scripts generated: {len(self.execution_context['generated_scripts'])}")
        print(f"Explanations given: {len(self.execution_context['explanations'])}")
        
        return {
            "goal": goal,
            "steps": len(self.react_history),
            "context": self.execution_context,
            "history": [step.model_dump() for step in self.react_history]
        }


async def demo_react():
    """Demo the ReAct loop"""
    system = FullAgenticSystem(model="qwen3-coder:latest")
    
    goal = """Help me set up a GPU training job:
1. Explain what GRES is
2. Generate a job script for 4 GPUs with 32GB memory
3. Validate the script
4. Save it for execution"""

    await system.run_react_loop(goal, max_steps=8)


async def demo_complex():
    """Demo with a complex multi-step request"""
    system = FullAgenticSystem(model="qwen3-coder:latest")
    
    goal = """Complete workflow setup:
1. Explain distributed training concepts
2. Create a multi-node job (2 nodes, 8 GPUs total)  
3. Add job monitoring commands
4. Review and validate everything
5. Save the final script"""

    await system.run_react_loop(goal, max_steps=10)


if __name__ == "__main__":
    print("\n" + "="*60)
    print("SELECT DEMO:")
    print("1. Simple ReAct demo")
    print("2. Complex workflow demo")
    print("="*60)
    
    choice = input("\nChoice (1 or 2): ").strip()
    
    if choice == "2":
        asyncio.run(demo_complex())
    else:
        asyncio.run(demo_react())
