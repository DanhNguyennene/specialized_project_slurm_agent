"""
Advanced Agentic System with Planning (ReAct Pattern)

Architecture:
1. Planner Agent - Creates multi-step plans for complex requests
2. Chat Agent - User interface, explains concepts
3. Slurm Agent - Generates structured commands  
4. Executor Agent - Validates and executes
5. Critic Agent - Reviews plans and suggests improvements

Uses:
- Chain-of-Thought reasoning
- Plan → Execute → Observe → Replan loop
- Handoffs between specialized agents
- Knowledge base for learning
"""
import asyncio
from typing import List, Dict, Any, Optional, Callable, Literal
from pydantic import BaseModel, Field
from enum import Enum
import json
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============ Pydantic Models for Planning ============

class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class Task(BaseModel):
    """A single task in a plan"""
    id: int
    title: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    agent: str = "planner"  # Which agent handles this
    dependencies: List[int] = []  # Task IDs this depends on
    result: Optional[str] = None
    
    
class Plan(BaseModel):
    """A complete plan with multiple tasks"""
    goal: str
    reasoning: str  # Why this plan was chosen
    tasks: List[Task]
    current_task_id: Optional[int] = None
    

class AgentThought(BaseModel):
    """Agent's reasoning step (Chain-of-Thought)"""
    observation: str  # What the agent sees/knows
    thought: str  # What the agent thinks
    action: str  # What action to take
    action_input: Optional[str] = None  # Input for the action


# ============ Agent Base Class ============

class Agent(BaseModel):
    """Agent with instructions, tools, and handoff capabilities"""
    name: str
    role: str  # Short description of role
    model: str = "qwen3-coder:latest"
    instructions: str
    tools: List[str] = []  # Tool names this agent can use
    
    class Config:
        arbitrary_types_allowed = True


# ============ Main Agentic System ============

class AgenticSlurmSystem:
    """
    Advanced multi-agent system with planning capabilities
    
    Flow:
    1. User request → Planner analyzes and creates plan
    2. Plan → Task execution with appropriate agents
    3. Each task: Observe → Think → Act → Observe
    4. Critic reviews, suggests improvements
    5. Results compiled and returned to user
    """
    
    def __init__(self, model: str = "qwen3-coder:latest"):
        self.model = model
        
        # Initialize OpenAI client
        import sys
        sys.path.insert(0, '/mnt/e/workspace/uni/specialized_project/danh_agent/agent')
        from utils.openai_client import OllamaClient
        self.client = OllamaClient(model=model)
        
        # Knowledge base
        self.knowledge_base = {
            "plans": [],
            "executions": [],
            "slurm_outputs": [],
            "user_feedback": []
        }
        
        # Current state
        self.current_plan: Optional[Plan] = None
        self.conversation_history: List[Dict] = []
        
        # Initialize agents
        self._init_agents()
        
    def _init_agents(self):
        """Initialize all specialized agents"""
        
        self.planner = Agent(
            name="Planner",
            role="Strategic Planning",
            instructions="""You are a strategic planner for Slurm HPC operations.

Your job is to:
1. Analyze complex user requests
2. Break them down into actionable tasks
3. Identify dependencies between tasks
4. Assign each task to the appropriate agent
5. Create a clear, executable plan

Think step-by-step:
- What is the user trying to achieve?
- What sub-tasks are needed?
- In what order should they be executed?
- Which agent should handle each task?

Available agents:
- chat: Answer questions, explain concepts
- slurm: Generate Slurm commands
- executor: Validate and execute commands
- critic: Review and improve plans

Output your plan as a structured list of tasks."""
        )
        
        self.chat_agent = Agent(
            name="Chat Agent",
            role="User Interaction",
            instructions="""You are a friendly Slurm expert assistant.

Your job is to:
1. Answer user questions about Slurm
2. Explain HPC concepts in simple terms
3. Provide best practices and tips
4. Guide users through their workflow

Be conversational but concise. Use examples when helpful."""
        )
        
        self.slurm_agent = Agent(
            name="Slurm Agent", 
            role="Command Generation",
            instructions="""You are a Slurm command specialist.

Your job is to:
1. Generate precise Slurm commands
2. Create job submission scripts
3. Validate resource requests
4. Optimize job configurations

Always use proper Slurm syntax and include:
- Required resources (nodes, CPUs, memory, GPUs)
- Time limits
- Partition selection
- Output file handling"""
        )
        
        self.executor = Agent(
            name="Executor",
            role="Command Execution",
            instructions="""You are a Slurm execution specialist.

Your job is to:
1. Validate commands before execution
2. Check for potential issues
3. Execute commands safely
4. Report results clearly

Always verify:
- Command syntax is correct
- Resources requested are reasonable
- No dangerous operations without confirmation"""
        )
        
        self.critic = Agent(
            name="Critic",
            role="Plan Review",
            instructions="""You are a critical reviewer for Slurm operations.

Your job is to:
1. Review plans for completeness
2. Identify potential issues
3. Suggest improvements
4. Validate results

Ask yourself:
- Does this plan fully address the user's goal?
- Are there any missing steps?
- Could anything go wrong?
- Is there a better approach?"""
        )
        
    # ============ Planning Methods ============
    
    async def create_plan(self, user_request: str) -> Plan:
        """
        Create a multi-step plan for a user request
        Uses Chain-of-Thought reasoning
        """
        logger.info(f"📋 Creating plan for: {user_request}")
        
        # Planning prompt with CoT
        planning_prompt = f"""Analyze this user request and create a detailed plan.

USER REQUEST: {user_request}

Think step-by-step:
1. What is the user's ultimate goal?
2. What information do I need to gather?
3. What commands need to be generated?
4. What needs to be validated or executed?
5. What should I explain to the user?

Create a plan with specific tasks. For each task specify:
- id: Sequential number (1, 2, 3...)
- title: Short task name
- description: What needs to be done
- agent: Which agent handles it (chat/slurm/executor/critic)
- dependencies: List of task IDs that must complete first

Respond in JSON format:
{{
    "goal": "The user's ultimate goal",
    "reasoning": "Why this plan will work",
    "tasks": [
        {{
            "id": 1,
            "title": "Task name",
            "description": "What to do",
            "agent": "agent_name",
            "dependencies": []
        }}
    ]
}}"""

        try:
            response = await self.client.chat(
                messages=[
                    {"role": "system", "content": self.planner.instructions},
                    {"role": "user", "content": planning_prompt}
                ],
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            plan_data = json.loads(content)
            
            # Parse tasks
            tasks = []
            for task_data in plan_data.get("tasks", []):
                task = Task(
                    id=task_data["id"],
                    title=task_data["title"],
                    description=task_data["description"],
                    agent=task_data.get("agent", "chat"),
                    dependencies=task_data.get("dependencies", []),
                    status=TaskStatus.PENDING
                )
                tasks.append(task)
            
            plan = Plan(
                goal=plan_data.get("goal", user_request),
                reasoning=plan_data.get("reasoning", ""),
                tasks=tasks
            )
            
            self.current_plan = plan
            self.knowledge_base["plans"].append({
                "request": user_request,
                "plan": plan.model_dump(),
                "timestamp": datetime.now().isoformat()
            })
            
            return plan
            
        except Exception as e:
            logger.error(f"Planning failed: {e}")
            # Fallback: simple single-task plan
            return Plan(
                goal=user_request,
                reasoning="Fallback plan due to parsing error",
                tasks=[
                    Task(
                        id=1,
                        title="Handle request",
                        description=user_request,
                        agent="slurm"
                    )
                ]
            )
    
    async def execute_task(self, task: Task) -> str:
        """
        Execute a single task using the appropriate agent
        Returns the result as a string
        """
        logger.info(f"⚙️ Executing task {task.id}: {task.title}")
        
        task.status = TaskStatus.IN_PROGRESS
        
        try:
            if task.agent == "chat":
                result = await self._run_chat_task(task)
            elif task.agent == "slurm":
                result = await self._run_slurm_task(task)
            elif task.agent == "executor":
                result = await self._run_executor_task(task)
            elif task.agent == "critic":
                result = await self._run_critic_task(task)
            else:
                result = await self._run_chat_task(task)  # Default to chat
            
            task.status = TaskStatus.COMPLETED
            task.result = result
            
            return result
            
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.result = f"Error: {e}"
            logger.error(f"Task {task.id} failed: {e}")
            return f"Task failed: {e}"
    
    async def _run_chat_task(self, task: Task) -> str:
        """Run a task using the Chat Agent"""
        response = await self.client.chat(
            messages=[
                {"role": "system", "content": self.chat_agent.instructions},
                {"role": "user", "content": task.description}
            ]
        )
        return response.choices[0].message.content
    
    async def _run_slurm_task(self, task: Task) -> str:
        """Run a task using the Slurm Agent with structured output"""
        from flow.slurm_structured_agent import SlurmStructuredAgent
        from utils.slurm_commands import SlurmCommandSequence, SlurmCommandBuilder
        
        slurm_agent = SlurmStructuredAgent(model=self.model)
        result = await slurm_agent.plan_only(task.description)
        
        # Store for learning
        self.knowledge_base["slurm_outputs"].append({
            "task": task.description,
            "result": result["sequence"],
            "timestamp": datetime.now().isoformat()
        })
        
        # Build and return script
        sequence = SlurmCommandSequence(**result["sequence"])
        builder = SlurmCommandBuilder()
        script = builder.compile_to_shell(sequence)
        
        return f"Generated {len(sequence.commands)} commands:\n\n{script}"
    
    async def _run_executor_task(self, task: Task) -> str:
        """Run a task using the Executor Agent"""
        # For now, just validate - actual execution would require Slurm connection
        response = await self.client.chat(
            messages=[
                {"role": "system", "content": self.executor.instructions},
                {"role": "user", "content": f"Validate and review this execution request:\n\n{task.description}"}
            ]
        )
        return response.choices[0].message.content
    
    async def _run_critic_task(self, task: Task) -> str:
        """Run a task using the Critic Agent"""
        # Include completed task results for context
        completed_results = []
        if self.current_plan:
            for t in self.current_plan.tasks:
                if t.status == TaskStatus.COMPLETED and t.result:
                    completed_results.append(f"Task {t.id} ({t.title}): {t.result[:500]}...")
        
        context = "\n\n".join(completed_results) if completed_results else "No completed tasks yet."
        
        response = await self.client.chat(
            messages=[
                {"role": "system", "content": self.critic.instructions},
                {"role": "user", "content": f"Review this plan and its execution so far:\n\nGoal: {self.current_plan.goal if self.current_plan else 'Unknown'}\n\nCompleted tasks:\n{context}\n\nRequest: {task.description}"}
            ]
        )
        return response.choices[0].message.content
    
    async def execute_plan(self, plan: Plan) -> Dict[str, Any]:
        """
        Execute all tasks in a plan, respecting dependencies
        """
        logger.info(f"🚀 Executing plan: {plan.goal}")
        
        results = []
        completed_ids = set()
        
        # Execute tasks in order, respecting dependencies
        max_iterations = len(plan.tasks) * 2  # Prevent infinite loops
        iteration = 0
        
        while len(completed_ids) < len(plan.tasks) and iteration < max_iterations:
            iteration += 1
            
            for task in plan.tasks:
                if task.id in completed_ids:
                    continue
                
                # Check dependencies
                deps_met = all(dep_id in completed_ids for dep_id in task.dependencies)
                if not deps_met:
                    continue
                
                # Execute task
                print(f"\n{'='*60}")
                print(f"📌 Task {task.id}/{len(plan.tasks)}: {task.title}")
                print(f"   Agent: {task.agent}")
                print(f"   Description: {task.description}")
                print('='*60)
                
                result = await self.execute_task(task)
                
                print(f"\n✅ Result:\n{result[:500]}{'...' if len(result) > 500 else ''}")
                
                results.append({
                    "task_id": task.id,
                    "title": task.title,
                    "agent": task.agent,
                    "result": result,
                    "status": task.status.value
                })
                
                completed_ids.add(task.id)
        
        return {
            "goal": plan.goal,
            "reasoning": plan.reasoning,
            "total_tasks": len(plan.tasks),
            "completed_tasks": len(completed_ids),
            "results": results
        }
    
    # ============ Main Entry Point ============
    
    async def run(self, user_request: str) -> Dict[str, Any]:
        """
        Main entry point: Plan and execute a user request
        
        1. Create plan
        2. Show plan to user
        3. Execute plan
        4. Return results
        """
        print("\n" + "🌟"*30)
        print("AGENTIC SLURM SYSTEM")
        print("🌟"*30)
        
        print(f"\n👤 User Request: {user_request}")
        
        # Phase 1: Planning
        print(f"\n{'='*60}")
        print("📋 PHASE 1: PLANNING")
        print('='*60)
        
        plan = await self.create_plan(user_request)
        
        print(f"\n🎯 Goal: {plan.goal}")
        print(f"\n💭 Reasoning: {plan.reasoning}")
        print(f"\n📝 Tasks ({len(plan.tasks)}):")
        for task in plan.tasks:
            deps = f" (depends on: {task.dependencies})" if task.dependencies else ""
            print(f"   {task.id}. [{task.agent}] {task.title}{deps}")
        
        # Phase 2: Execution
        print(f"\n{'='*60}")
        print("⚡ PHASE 2: EXECUTION")
        print('='*60)
        
        results = await self.execute_plan(plan)
        
        # Phase 3: Summary
        print(f"\n{'='*60}")
        print("📊 PHASE 3: SUMMARY")
        print('='*60)
        
        print(f"\n✅ Completed: {results['completed_tasks']}/{results['total_tasks']} tasks")
        
        # Store for learning
        self.knowledge_base["executions"].append({
            "request": user_request,
            "results": results,
            "timestamp": datetime.now().isoformat()
        })
        
        print("\n" + "🌟"*30)
        print("EXECUTION COMPLETE")
        print("🌟"*30)
        
        return results


# ============ Test/Demo ============

async def demo():
    """Demo the agentic system with a complex request"""
    
    system = AgenticSlurmSystem(model="qwen3-coder:latest")
    
    # Complex multi-step request
    request = """I need help setting up a complete machine learning workflow:
1. First, explain what resources I typically need for training a transformer model
2. Then create a job submission script for distributed training with 4 nodes and 8 GPUs total
3. Also show me how to check if my job is running correctly
4. Finally, review the whole setup and suggest any improvements"""

    results = await system.run(request)
    
    print("\n\n" + "="*60)
    print("FINAL RESULTS")
    print("="*60)
    
    for result in results["results"]:
        print(f"\n--- Task {result['task_id']}: {result['title']} ---")
        print(f"Agent: {result['agent']}")
        print(f"Status: {result['status']}")
        print(f"Result preview: {result['result'][:300]}...")


if __name__ == "__main__":
    asyncio.run(demo())
