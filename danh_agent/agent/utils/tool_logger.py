import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, asdict
from pathlib import Path
import uuid

@dataclass
class ToolExecution:
    """Single tool execution record for agent feedback"""
    execution_id: str
    tool_name: str
    inputs: Dict[str, Any]
    outputs: Dict[str, Any]
    success: bool
    error_message: Optional[str]
    execution_time_ms: int
    timestamp: str
    context: Dict[str, Any]

@dataclass 
class AgentStep:
    """Single reasoning step for agent feedback"""
    step_id: str
    task_id: str
    step_number: int
    agent_reasoning: str
    tools_called: List[str]
    step_outcome: str
    success: bool
    timestamp: str

@dataclass
class TaskTrace:
    """Complete task execution trace for agent learning"""
    task_id: str
    original_request: str
    agent_plan: str
    steps: List[AgentStep]
    tool_executions: List[ToolExecution]
    final_outcome: str
    success: bool
    total_time_ms: int
    lessons_learned: List[str]
    timestamp: str

class AgentLogger:
    """Simplified logger optimized for agent feedback and self-improvement"""
    
    def __init__(self, log_dir: str = "./agent_logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        # Current tracking
        self.current_task: Optional[TaskTrace] = None
        self.current_step: Optional[AgentStep] = None
        self.step_counter = 0
        
        # Files for different feedback types
        self.execution_log = self.log_dir / "executions.jsonl"
        self.success_patterns = self.log_dir / "success_patterns.jsonl" 
        self.failure_analysis = self.log_dir / "failures.jsonl"
        self.agent_feedback = self.log_dir / "agent_feedback.jsonl"
    
    def start_task(self, task_id: str, request: str, agent_plan: str) -> str:
        """Start tracking a new task execution"""
        self.current_task = TaskTrace(
            task_id=task_id,
            original_request=request,
            agent_plan=agent_plan,
            steps=[],
            tool_executions=[],
            final_outcome="",
            success=False,
            total_time_ms=0,
            lessons_learned=[],
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        self.step_counter = 0
        return task_id
    
    def start_step(self, agent_reasoning: str) -> str:
        """Start tracking an agent reasoning step"""
        if not self.current_task:
            raise ValueError("No active task")
            
        self.step_counter += 1
        step_id = f"{self.current_task.task_id}_step_{self.step_counter}"
        
        self.current_step = AgentStep(
            step_id=step_id,
            task_id=self.current_task.task_id,
            step_number=self.step_counter,
            agent_reasoning=agent_reasoning,
            tools_called=[],
            step_outcome="",
            success=False,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        return step_id
    
    def log_tool_execution(self, tool_name: str, inputs: Dict[str, Any], 
                          outputs: Dict[str, Any], success: bool, 
                          execution_time_ms: int, error: str = None) -> str:
        """Log a tool execution with agent context"""
        if not self.current_task or not self.current_step:
            raise ValueError("No active task/step")
            
        execution_id = str(uuid.uuid4())
        
        execution = ToolExecution(
            execution_id=execution_id,
            tool_name=tool_name,
            inputs=inputs,
            outputs=outputs,
            success=success,
            error_message=error,
            execution_time_ms=execution_time_ms,
            timestamp=datetime.now(timezone.utc).isoformat(),
            context={
                "task_id": self.current_task.task_id,
                "step_id": self.current_step.step_id,
                "agent_reasoning": self.current_step.agent_reasoning,
                "step_number": self.current_step.step_number
            }
        )
        
        # Add to current tracking
        self.current_task.tool_executions.append(execution)
        self.current_step.tools_called.append(tool_name)
        
        # Write execution log immediately for real-time feedback
        self._write_jsonl(self.execution_log, asdict(execution))
        
        return execution_id
    
    def end_step(self, outcome: str, success: bool):
        """End current step with outcome"""
        if not self.current_step:
            return
            
        self.current_step.step_outcome = outcome
        self.current_step.success = success
        
        # Add to task
        if self.current_task:
            self.current_task.steps.append(self.current_step)
        
        self.current_step = None
    
    def end_task(self, final_outcome: str, success: bool, lessons: List[str] = None):
        """End task and generate feedback logs"""
        if not self.current_task:
            return
            
        self.current_task.final_outcome = final_outcome
        self.current_task.success = success
        self.current_task.lessons_learned = lessons or []
        
        # Calculate total time
        if self.current_task.tool_executions:
            self.current_task.total_time_ms = sum(
                exec.execution_time_ms for exec in self.current_task.tool_executions
            )
        
        # Generate different types of feedback logs
        self._generate_feedback_logs()
        
        # Reset current task
        self.current_task = None
    
    def _generate_feedback_logs(self):
        """Generate simplified feedback logs for agent learning"""
        if not self.current_task:
            return
            
        # 1. Success Pattern Analysis
        if self.current_task.success:
            success_pattern = {
                "task_type": self._classify_task_type(self.current_task.original_request),
                "successful_sequence": [step.agent_reasoning for step in self.current_task.steps],
                "effective_tools": list(set(exec.tool_name for exec in self.current_task.tool_executions if exec.success)),
                "execution_time": self.current_task.total_time_ms,
                "key_insights": self.current_task.lessons_learned,
                "timestamp": self.current_task.timestamp
            }
            self._write_jsonl(self.success_patterns, success_pattern)
        
        # 2. Failure Analysis
        else:
            failed_tools = [exec for exec in self.current_task.tool_executions if not exec.success]
            failure_analysis = {
                "task_type": self._classify_task_type(self.current_task.original_request),
                "failure_point": self._identify_failure_point(),
                "failed_tools": [{"tool": exec.tool_name, "error": exec.error_message, "inputs": exec.inputs} for exec in failed_tools],
                "timestamp": self.current_task.timestamp
            }
            self._write_jsonl(self.failure_analysis, failure_analysis)
        
        # 3. Agent Feedback Summary
        feedback = {
            "task_id": self.current_task.task_id,
            "request": self.current_task.original_request,
            "success": self.current_task.success,
            "steps_taken": len(self.current_task.steps),
            "tools_used": len(self.current_task.tool_executions),
            "efficiency_score": self._calculate_efficiency(),
            "timestamp": self.current_task.timestamp
        }
        self._write_jsonl(self.agent_feedback, feedback)
    
    def get_recent_logs(self, limit: int = 10) -> Dict[str, Any]:
        """Get recent execution data for debugging and monitoring"""
        return {
            "recent_executions": self._read_recent_jsonl(self.execution_log, limit),
            "recent_successes": self._read_recent_jsonl(self.success_patterns, limit),
            "recent_failures": self._read_recent_jsonl(self.failure_analysis, limit),
            "recent_feedback": self._read_recent_jsonl(self.agent_feedback, limit),
            "tool_stats": self._get_tool_stats()
        }
    
    def get_logs_by_time(self, hours_back: int = 1) -> Dict[str, Any]:
        """Get logs from the last N hours"""
        cutoff_time = datetime.now(timezone.utc).timestamp() - (hours_back * 3600)
        
        recent_logs = []
        if self.execution_log.exists():
            with open(self.execution_log, 'r') as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        log_time = datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00')).timestamp()
                        if log_time >= cutoff_time:
                            recent_logs.append(data)
                    except (json.JSONDecodeError, KeyError, ValueError):
                        continue
        
        return {
            "time_range": f"Last {hours_back} hour(s)",
            "log_count": len(recent_logs),
            "logs": recent_logs
        }
    
    def _classify_task_type(self, task: str) -> str:
        """Classify task type for pattern matching"""
        task_lower = task.lower()
        
        if any(word in task_lower for word in ['deploy', 'install', 'setup', 'configure']):
            return "deployment"
        elif any(word in task_lower for word in ['monitor', 'check', 'status', 'list']):
            return "monitoring"  
        elif any(word in task_lower for word in ['file', 'read', 'write', 'create']):
            return "file_management"
        elif any(word in task_lower for word in ['docker', 'container', 'service']):
            return "container_management"
        elif any(word in task_lower for word in ['debug', 'error', 'log', 'troubleshoot']):
            return "debugging"
        else:
            return "general"
    
    def _identify_failure_point(self) -> Dict[str, Any]:
        """Identify where the task failed"""
        if not self.current_task:
            return {}
            
        failed_steps = [step for step in self.current_task.steps if not step.success]
        failed_tools = [exec for exec in self.current_task.tool_executions if not exec.success]
        
        if failed_steps:
            return {
                "type": "step_failure",
                "step_number": failed_steps[0].step_number,
                "reasoning": failed_steps[0].agent_reasoning
            }
        elif failed_tools:
            return {
                "type": "tool_failure", 
                "tool": failed_tools[0].tool_name,
                "error": failed_tools[0].error_message
            }
        else:
            return {"type": "unknown"}
    
    def _calculate_efficiency(self) -> float:
        """Calculate task execution efficiency score"""
        if not self.current_task:
            return 0.0
            
        # Simple efficiency: success rate of tools vs time taken
        total_tools = len(self.current_task.tool_executions)
        successful_tools = sum(1 for exec in self.current_task.tool_executions if exec.success)
        
        if total_tools == 0:
            return 0.0
            
        success_rate = successful_tools / total_tools
        time_penalty = min(1.0, 60000 / max(self.current_task.total_time_ms, 1000))  # Penalty for >60s
        
        return success_rate * time_penalty
    
    def _get_tool_stats(self) -> Dict[str, Any]:
        """Get simple statistics about tool usage"""
        tool_stats = {}
        
        if self.execution_log.exists():
            with open(self.execution_log, 'r') as f:
                for line in f:
                    try:
                        exec_data = json.loads(line)
                        tool = exec_data['tool_name']
                        
                        if tool not in tool_stats:
                            tool_stats[tool] = {"total": 0, "success": 0}
                        
                        tool_stats[tool]["total"] += 1
                        if exec_data["success"]:
                            tool_stats[tool]["success"] += 1
                    except (json.JSONDecodeError, KeyError):
                        continue
        
        # Calculate success rates
        for tool in tool_stats:
            stats = tool_stats[tool]
            stats["success_rate"] = stats["success"] / stats["total"] if stats["total"] > 0 else 0
        
        return tool_stats
    
    def _write_jsonl(self, file_path: Path, data: Dict[str, Any]):
        """Write JSON line to file"""
        try:
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(data, ensure_ascii=False) + '\n')
        except Exception as e:
            print(f"Failed to write to {file_path}: {e}")
    
    def _read_recent_jsonl(self, file_path: Path, limit: int) -> List[Dict[str, Any]]:
        """Read recent entries from JSONL file"""
        if not file_path.exists():
            return []
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            recent_lines = lines[-limit:] if len(lines) >= limit else lines
            result = []
            for line in recent_lines:
                try:
                    result.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return result
        except Exception as e:
            print(f"Failed to read from {file_path}: {e}")
            return []

# Example usage
if __name__ == "__main__":
    # Create logger
    logger = AgentLogger()
    
    # Example task tracking
    task_id = logger.start_task(
        task_id="task_001",
        request="Check system status on VM",
        agent_plan="1. Connect to VM 2. Check system info 3. Report results"
    )
    
    # Example step tracking
    step_id = logger.start_step("Connecting to VM and checking system status")
    
    # Example tool execution
    logger.log_tool_execution(
        tool_name="vm_shell_command",
        inputs={"command": "uname -a", "vm_ip": "192.168.1.100"},
        outputs={"success": True, "content": "Linux ubuntu 5.4.0"},
        success=True,
        execution_time_ms=1500
    )
    
    # End step and task
    logger.end_step("Successfully checked system status", True)
    logger.end_task("System status retrieved successfully", True, ["VM is running Ubuntu"])
    
    # Get recent logs
    recent_logs = logger.get_recent_logs(5)
    print("Recent logs:", json.dumps(recent_logs, indent=2))