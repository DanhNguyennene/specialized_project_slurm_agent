"""
VMAgent rewritten to use OpenAI SDK for local Ollama execution
Replaces LangChain/LangGraph with OpenAI SDK framework
"""
import asyncio
import json
import logging
from typing import Dict, Any, List, Optional, TypedDict
from dataclasses import dataclass
from datetime import datetime, timezone
import time as time_module
import os
from dotenv import load_dotenv
import aiohttp
import uuid
from copy import deepcopy
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator

from utils.openai_adapter import OllamaOpenAIAdapter, create_ollama_client
from utils.tools_openai import (
    SLURM_FUNCTION_DEFINITIONS, 
    SlurmToolExecutor,
    slurm_connection_manager
)
from utils.prompt import PromptDict
from utils.tool_logger import AgentLogger

load_dotenv()

# Configuration
CHROMA_HOST = os.getenv("CHROMA_HOST", "http://10.0.0.1:12000")
MULTIPASS_URL = os.getenv("MULTIPASS_URL", "http://10.0.0.01:8010/")
VM_CLOUD_INIT_PATH = os.getenv("VM_CLOUD_INIT_PATH", "/home/danhvuive/image-init.yaml")
BASE_OLLAMA_URL = "http://localhost:11434/v1"
OLLAMA_MODEL = "gpt-oss:120b-cloud"
ENV_IP = os.getenv("ENV_IP", "10.1.1.2")
ENV_PORT = int(os.getenv("ENV_PORT", "32222"))
ENV_WORKING_DIR = os.getenv("ENV_WORKING_DIR", "/mnt/e/workspace/tma/tma_agent/test_env")

UTC = timezone.utc
agent_logger = logging.getLogger("Agent 007")
agent_logger.setLevel(logging.DEBUG)


class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'


def print_thinking(content: str):
    print(f"\n{Colors.MAGENTA}{'='*50}")
    print(f"{Colors.BOLD}🧠 THINKING PROCESS{Colors.END}")
    print(f"{Colors.MAGENTA}{'='*50}{Colors.END}")
    print(f"{Colors.CYAN}{content}{Colors.END}")
    print(f"{Colors.MAGENTA}{'='*50}{Colors.END}\n")


def print_tool_message(tool_msg: str):
    print(f"\n{Colors.YELLOW}{'─'*30}")
    print(f"{Colors.BOLD}🔧 TOOL OUTPUT{Colors.END}")
    print(f"{Colors.YELLOW}{'─'*30}{Colors.END}")
    print(f"{Colors.WHITE}{tool_msg}{Colors.END}")
    print(f"{Colors.YELLOW}{'─'*30}{Colors.END}\n")


def print_final_response(response: str):
    print(f"\n{Colors.GREEN}{'='*40}")
    print(f"{Colors.BOLD}📤 FINAL RESPONSE{Colors.END}")
    print(f"{Colors.GREEN}{'='*40}{Colors.END}")
    print(f"{Colors.CYAN}{response}{Colors.END}")
    print(f"{Colors.GREEN}{'='*40}{Colors.END}\n")


class AgentState:
    """State management for the agent"""
    
    def __init__(self):
        self.agent_id: str = "default-agent"
        self.cluster_ip: Optional[str] = ENV_IP
        self.cluster_port: int = ENV_PORT
        self.env_working_dir: str = ENV_WORKING_DIR
        self.messages: List[Dict[str, Any]] = []
        self.system_prompt: str = ""
        self.context: List[str] = []
        self.thinking: List[str] = []
        self.response: str = ""
        self.task: str = "chat"
        self.logs: List[str] = []
        self.attempt: int = 0
        self.rag_query: List[str] = []
        self.summarized_logs: List[str] = []
        self.summarized_tools: List[str] = []
        self.final_response: str = ""
        self.use_vm: bool = False


class VMAgent:
    """LangGraph-style agent using OpenAI SDK with local Ollama"""
    
    def __init__(self, model: Optional[OllamaOpenAIAdapter] = None):
        self.model = model or create_ollama_client(
            model=OLLAMA_MODEL,
            base_url=BASE_OLLAMA_URL,
            temperature=0.0
        )
        self.prompt_dict = PromptDict()
        self.logger = AgentLogger()
        self.config = {
            "recursion_limit": 1000,
        }
        self.max_log = 3
    
    async def _init_state(self, state: AgentState) -> AgentState:
        """Initialize agent state"""
        state.cluster_ip = ENV_IP
        state.cluster_port = ENV_PORT
        state.env_working_dir = ENV_WORKING_DIR
        state.attempt = 1
        return state
    
    async def _query_rag(self, state: AgentState):
        """Query RAG system for relevant context"""
        agent_logger.info("Node: Query_Rag")
        
        try:
            # Get user messages
            user_messages = [msg for msg in state.messages if msg.get("role") == "user"]
            
            # Generate RAG query using model
            rag_prompt = self.prompt_dict.substitute('query_rag.txt', {
                "thinking": state.thinking[-1] if state.thinking else "",
            })
            
            messages = [
                {"role": "system", "content": rag_prompt},
                *user_messages
            ]
            
            response = await self.model.invoke(messages)
            query_text = response["content"]
            
            agent_logger.debug(f"RAG Query: {query_text}")
            
            # Query ChromaDB
            async with aiohttp.ClientSession() as session:
                body = {
                    "collection_name": "WebUI_Markdown",
                    "query": query_text,
                    "n_result": 5,
                }
                async with session.post(f"{CHROMA_HOST}/query_collection", json=body) as resp:
                    result = await resp.json()
                    documents = result.get("result", [])
                    
                    context = [doc.get("document", "") for doc in documents]
                    agent_logger.debug(f"Retrieved {len(context)} documents")
                    
                    state.context = context
                    state.rag_query.append(query_text)
                    
                    return state
                    
        except Exception as e:
            agent_logger.error(f"Error querying RAG: {e}")
            raise e
    
    async def _planning_execution(self, state: AgentState):
        """Generate execution plan"""
        agent_logger.debug("Node: planning_execution")
        
        # Prepare context
        contexts = "\n".join(f"\nRELEVANT CONTEXT {i + 1}\n{ctx}\n" 
                            for i, ctx in enumerate(state.context))
        
        logs = "\n".join(f"\nATTEMPT {i + 1}\n{log}\n" 
                        for i, log in enumerate(state.summarized_logs))
        
        rag_logs = "\n".join(f"\nRAG QUERY {i + 1}\n{q}\n" 
                            for i, q in enumerate(state.rag_query[-100:]))
        
        substitution_data = {
            "given_context": contexts,
            "extracted_logs": logs,
            "rag_querys": rag_logs,
            "logs_count": len(state.summarized_logs),
            "rag_count": len(state.rag_query),
            "summarized_tools": "\n".join(state.summarized_tools),
        }
        
        prompt = self.prompt_dict.substitute('planning_execution.txt', substitution_data)
        
        # Get user messages
        user_messages = [msg for msg in state.messages if msg.get("role") == "user"]
        
        messages = [
            *user_messages,
            {"role": "system", "content": prompt}
        ]
        
        # Generate plan
        max_retries = 3
        for attempt in range(max_retries):
            response = await self.model.invoke(messages)
            plan = response["content"]
            
            if plan and plan.strip():
                print_thinking(plan)
                state.thinking.append(plan)
                return state
            
            agent_logger.warning(f"Empty plan on attempt {attempt + 1}, retrying...")
        
        # Fallback
        state.thinking.append("Failed to generate valid plan")
        return state
    
    async def _should_retrieval(self, state: AgentState) -> str:
        """Determine next routing step"""
        
        routing_prompt = """
        You are a ROUTING DECISION AGENT. Analyze the strategic plan and determine the next action.

        CURRENT STATE:
        - Strategic Plan: {planning_output}

        ROUTING RULES:
        1. "RAG_NEEDED" - if plan mentions "Search RAG", "documentation", "lookup"
        2. "EXECUTE_TOOLS" - if plan contains "Execute" followed by specific tool/command
        3. "GENERATE_FINAL" - if plan indicates task completion or "Generate final answer"

        OUTPUT one of: RAG_NEEDED, EXECUTE_TOOLS, GENERATE_FINAL
        """
        
        planning_output = state.thinking[-1] if state.thinking else ""
        
        formatted_prompt = routing_prompt.format(planning_output=planning_output)
        
        messages = [{"role": "user", "content": formatted_prompt}]
        response = await self.model.invoke(messages)
        decision = response["content"].strip()
        
        if "RAG_NEEDED" in decision:
            print(f"Routing: RAG_NEEDED")
            return "call_rag"
        elif "EXECUTE_TOOLS" in decision:
            print(f"Routing: EXECUTE_TOOLS")
            return "continue"
        elif "GENERATE_FINAL" in decision:
            print(f"Routing: GENERATE_FINAL")
            return "generate_final"
        else:
            print(f"Routing: CONTINUE (fallback)")
            return "continue"
    
    async def _prepare_prompt(self, state: AgentState):
        """Prepare prompt for tool execution"""
        agent_logger.debug("Node: prepare_prompt")
        
        thinking = state.thinking[-1] if state.thinking else ""
        logs = "\n".join(f"ATTEMPT {i + 1}\n{log}" 
                        for i, log in enumerate(state.summarized_logs[-self.max_log:]))
        
        prompt = self.prompt_dict.substitute('prepare_prompt.txt', {
            "thinking": thinking,
            "logs": logs,
        })
        
        state.system_prompt = prompt
        
        # Register VM if needed
        cluster_ip = await self.register_vm(state)
        state.cluster_ip = cluster_ip
        state.attempt += 1
        
        print(f"Connecting to cluster at {cluster_ip}:{state.cluster_port}")
        
        return state
    
    async def call_model(self, state: AgentState) -> AgentState:
        """Call model with tool definitions"""
        print(f"Calling model with {len(state.messages)} messages")
        
        # Get user messages
        user_messages = [msg for msg in state.messages if msg.get("role") == "user"]
        
        messages = [
            {"role": "system", "content": state.system_prompt},
            *user_messages
        ]
        
        # Call with tools
        response = await self.model.chat_completion(
            messages=messages,
            tools=SLURM_FUNCTION_DEFINITIONS,
            tool_choice="auto"
        )
        
        # Extract response
        assistant_message = response.choices[0].message
        
        # Check for tool calls
        if assistant_message.tool_calls:
            print(f"Model requested {len(assistant_message.tool_calls)} tool call(s)")
            
            # Add assistant message with tool calls
            state.messages.append({
                "role": "assistant",
                "content": assistant_message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in assistant_message.tool_calls
                ]
            })
            
            # Execute tools
            state = await self._execute_tools(state, assistant_message.tool_calls)
        else:
            # No tool calls, add response
            state.messages.append({
                "role": "assistant",
                "content": assistant_message.content or ""
            })
        
        return state
    
    async def _execute_tools(self, state: AgentState, tool_calls):
        """Execute tool calls and add results to state"""
        
        executor = SlurmToolExecutor(
            cluster_ip=state.cluster_ip,
            cluster_port=state.cluster_port
        )
        
        for tool_call in tool_calls:
            function_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)
            
            print(f"Executing tool: {function_name}")
            
            # Execute the tool
            result = await executor.execute_function(function_name, arguments)
            
            print_tool_message(result[:500] + "..." if len(result) > 500 else result)
            
            # Add tool response to messages
            state.messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": function_name,
                "content": result
            })
            
            # Log the tool execution
            state.logs.append(result)
        
        return state
    
    async def log_summarizer(self, state: AgentState) -> AgentState:
        """Summarize tool execution logs"""
        
        if not state.logs:
            return state
        
        last_log = state.logs[-1]
        thinking = state.thinking[-1] if state.thinking else ""
        
        prompt = f"""
Summarize this tool execution result concisely.

Planning Context:
{thinking}

Tool Output:
{last_log}

Provide a brief summary (2-4 sentences) including:
- What the tool did
- Key results (job IDs, partition names, states, node names, etc.)
- Any errors or important status information

Preserve exact values like job IDs, paths, partition names, and node names.

Summary:
"""
        
        messages = [{"role": "user", "content": prompt}]
        response = await self.model.invoke(messages)
        summary = response["content"]
        
        state.summarized_logs.append(summary)
        
        print(f"Log summarized: {summary[:100]}...")
        
        return state
    
    async def _tools_summarizer(self, state: AgentState):
        """Summarize tools execution for planning context"""
        
        if not state.summarized_logs:
            return state
        
        summary_text = f"""
Tool Execution Summary:
- Total attempts: {len(state.summarized_logs)}
- Last execution: {state.summarized_logs[-1] if state.summarized_logs else 'None'}
"""
        
        state.summarized_tools.append(summary_text)
        
        return state
    
    async def generate_final(self, state: AgentState) -> AgentState:
        """Generate final response"""
        
        final_prompt = self.prompt_dict.substitute('final.txt', {
            "given_context": state.context,
            "thinking": "\n".join(f"THINKING SESSION {i + 1}\n{t}" 
                                 for i, t in enumerate(state.thinking)),
        })
        
        messages = [
            {"role": "system", "content": final_prompt},
            *state.messages
        ]
        
        response = await self.model.invoke(messages)
        state.final_response = response["content"]
        
        print_final_response(state.final_response)
        
        return state
    
    async def register_vm(self, state: AgentState) -> str:
        """Register or retrieve VM for agent"""
        
        if not state.use_vm:
            return ENV_IP
        
        if state.cluster_ip:
            return state.cluster_ip
        
        # Request VM from multipass
        try:
            async with aiohttp.ClientSession() as session:
                # Check for existing VM
                async with session.get(
                    f"{MULTIPASS_URL}get_free_assigned_vm/{state.agent_id}"
                ) as resp:
                    result = await resp.json()
                    
                    if result.get("data"):
                        vm_name = result['data'][0]['vm_name']
                        cluster_ip = result['data'][0]['info']['info']['info'][vm_name]['ipv4'][0]
                        return cluster_ip
                
                # Request new VM
                request_body = {
                    "agent_id": state.agent_id,
                    "cpu": 1,
                    "memory": "1G",
                    "disk": "5G",
                    "cloud_init": VM_CLOUD_INIT_PATH,
                    "priority": 0,
                    "enable_cloning": True
                }
                
                async with session.post(f"{MULTIPASS_URL}request_vm", json=request_body) as resp:
                    if resp.status == 200:
                        # Retrieve VM info
                        async with session.get(
                            f"{MULTIPASS_URL}get_free_assigned_vm/{state.agent_id}"
                        ) as get_resp:
                            result = await get_resp.json()
                            vm_name = result['data'][0]['vm_name']
                            cluster_ip = result['data'][0]['info']['info']['info'][vm_name]['ipv4'][0]
                            return cluster_ip
                    
                    return ENV_IP
                    
        except Exception as e:
            agent_logger.error(f"Failed to register VM: {e}")
            return ENV_IP
    
    async def run(self, user_input: List[Dict[str, Any]], thread_id: str) -> Dict[str, Any]:
        """Execute agent workflow"""
        
        # Initialize state
        state = AgentState()
        state.agent_id = thread_id
        state.messages = user_input
        
        state = await self._init_state(state)
        
        task_id = str(uuid.uuid4())
        start_time = time_module.time()
        
        try:
            # Execution loop (simplified version of LangGraph flow)
            max_iterations = 10
            
            for iteration in range(max_iterations):
                agent_logger.debug(f"Iteration {iteration + 1}")
                
                # Planning
                state = await self._planning_execution(state)
                
                # Routing decision
                next_step = await self._should_retrieval(state)
                
                if next_step == "call_rag":
                    # Query RAG
                    state = await self._query_rag(state)
                    continue
                    
                elif next_step == "generate_final":
                    # Generate final response
                    state = await self.generate_final(state)
                    break
                    
                else:  # continue / execute_tools
                    # Prepare and execute tools
                    state = await self._prepare_prompt(state)
                    state = await self.call_model(state)
                    state = await self.log_summarizer(state)
                    state = await self._tools_summarizer(state)
            
            # If no final response yet, generate one
            if not state.final_response:
                state = await self.generate_final(state)
            
            execution_time = int((time_module.time() - start_time) * 1000)
            
            return {
                "content": state.final_response,
                "thinking": "\n".join(f"**THINKING SESSION {i + 1}**\n{t}" 
                                     for i, t in enumerate(state.thinking)),
                "tool_calls": state.logs,
                "execution_time_ms": execution_time
            }
            
        except Exception as e:
            error_time = int((time_module.time() - start_time) * 1000)
            agent_logger.error(f"Execution failed: {e}")
            
            return {
                "success": False,
                "error": str(e),
                "task_id": task_id,
                "execution_time_ms": error_time
            }
    
    async def generate_answer_exclusive(self, user_input: List[Dict[str, Any]], thread_id: str) -> Dict[str, Any]:
        """Generate simple answer without tools"""
        response = await self.model.invoke(user_input)
        return {
            "content": response["content"]
        }


# Streaming support
async def generate_vm_agent_streaming_completion(user_input, thread_id):
    """Stream VMAgent execution"""
    
    async def stream_agent():
        try:
            # Initialize agent
            model = create_ollama_client(
                model=OLLAMA_MODEL,
                base_url=BASE_OLLAMA_URL,
                temperature=0.0
            )
            
            agent = VMAgent(model)
            
            # Convert messages
            messages = []
            for msg in user_input:
                if msg['role'] == 'user':
                    messages.append({"role": "user", "content": msg['content']})
                elif msg['role'] == 'system':
                    messages.append({"role": "system", "content": msg['content']})
                elif msg['role'] == 'assistant':
                    messages.append({"role": "assistant", "content": msg['content']})
            
            # Initialize state
            state = AgentState()
            state.agent_id = thread_id
            state.messages = messages
            state = await agent._init_state(state)
            
            # Stream execution
            max_iterations = 10
            
            for iteration in range(max_iterations):
                # Planning
                yield json.dumps({"type": "status", "content": f"Planning iteration {iteration + 1}..."}) + "\n"
                state = await agent._planning_execution(state)
                
                if state.thinking:
                    yield json.dumps({"type": "thinking", "content": state.thinking[-1]}) + "\n"
                
                # Routing
                next_step = await agent._should_retrieval(state)
                
                if next_step == "call_rag":
                    yield json.dumps({"type": "status", "content": "Querying knowledge base..."}) + "\n"
                    state = await agent._query_rag(state)
                    
                elif next_step == "generate_final":
                    yield json.dumps({"type": "status", "content": "Generating final response..."}) + "\n"
                    state = await agent.generate_final(state)
                    yield json.dumps({"type": "response", "content": state.final_response, "done": True}) + "\n"
                    break
                    
                else:
                    yield json.dumps({"type": "status", "content": "Executing tools..."}) + "\n"
                    state = await agent._prepare_prompt(state)
                    state = await agent.call_model(state)
                    
                    if state.logs:
                        yield json.dumps({"type": "tool_result", "content": state.logs[-1][:200]}) + "\n"
                    
                    state = await agent.log_summarizer(state)
                    state = await agent._tools_summarizer(state)
            
            if not state.final_response:
                state = await agent.generate_final(state)
                yield json.dumps({"type": "response", "content": state.final_response, "done": True}) + "\n"
                
        except Exception as e:
            yield json.dumps({"type": "error", "content": str(e)}) + "\n"
    
    return StreamingResponse(stream_agent(), media_type="text/event-stream")


# Main entry point for testing
async def main(input_messages):
    model = create_ollama_client(
        model=OLLAMA_MODEL,
        base_url=BASE_OLLAMA_URL,
        temperature=0.0
    )
    
    agent = VMAgent(model)
    
    result = await agent.run(
        user_input=[{"role": "user", "content": input_messages['content']}],
        thread_id="default-agent"
    )
    
    return result


if __name__ == "__main__":
    import asyncio
    user_input = {
        "role": "user",
        "content": "Check the status of the Slurm cluster"
    }
    
    response = asyncio.run(main(user_input))
    print(f"{Colors.GREEN}📤 Response: {Colors.END}{Colors.CYAN}{response}{Colors.END}")
