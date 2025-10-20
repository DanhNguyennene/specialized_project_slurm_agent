import asyncio
from email.mime import message
from ray import state
from sympy import true
import websockets
import json
import logging
from typing import Dict, Any, List, Optional, Annotated
from dataclasses import dataclass
from datetime import datetime, timezone
import time as time_module
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage,ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.language_models import BaseChatModel
import functools
from utils.tools import SlurmMCPConnection,SLURM_TOOLS
from typing import Dict, Any, List, Optional, TypedDict, Annotated,Union
import os
from dotenv import load_dotenv
import aiohttp
from utils.prompt import PromptDict
from utils.tool_logger import AgentLogger
import uuid
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import ToolNode
UTC = timezone.utc
from langchain_core.runnables import chain
import json
import time
import asyncio
from copy import deepcopy


load_dotenv()
CHROMA_HOST = os.getenv("CHROMA_HOST", "http://10.0.0.1:12000")
MULTIPASS_URL = os.getenv("MULTIPASS_URL", "http://10.0.0.01:8010/")
VM_CLOUD_INIT_PATH = os.getenv("VM_CLOUD_INIT_PATH", "/home/danhvuive/image-init.yaml")
agent_logger = logging.Logger(name="Agent 007")
agent_logger.setLevel(logging.DEBUG)
BASE_OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "gpt-oss:120b-cloud"
ENV_IP = os.getenv("ENV_IP", "10.1.1.2")
ENV_PORT = int(os.getenv("ENV_PORT", "32222"))
ENV_WORKING_DIR = os.getenv("ENV_WORKING_DIR", "/mnt/e/workspace/tma/tma_agent/test_env")
class AgentState(TypedDict):
    agent_id: str
    cluster_ip: Optional[str]  # VM name assigned to the agent
    cluster_port: Optional[int]  # VM name assigned to the agent
    env_working_dir: Optional[str]  # VM name assigned to the agent
    # chat_history: Annotated[List[str], "The messages in the conversation"]
    messages: Annotated[List, add_messages]
    system_prompt: Annotated[str, "The system prompt for the conversation"]
    context: Annotated[List[str], "The context query for the conversation use for context agent"]
    thinking: Annotated[List[AIMessage], "The thinking process in the conversation for action agent"]
    response: str
    results_tool_calls: Annotated[List[Dict[str, Any]], "The results of the tool calls"]
    task: Annotated[str, "for openweubui structure"]
    logs: Annotated[List[ToolMessage], "The logs collected from the VM"]
    attempt: Annotated[int, "The current attempt number"]
    log_file_paths: Annotated[set[str], "The set of log file paths"]
    rag_query: Annotated[List[str], "The list of RAG query messages"]
    summarized_logs: Annotated[List[str], "The summarized logs from the log summarizer"]
    final_response: Annotated[str, "The final response from the agent"]
    use_vm: Annotated[bool, "Whether to use a VM for the agent's tasks"]
    summarized_tools: Annotated[List[str], "The summarized tools from the tools summarizer"]

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
    END = '\033[0m'  # End color
def print_thinking(answer):
    content = answer.content if hasattr(answer, 'content') else str(answer)
    print(f"\n{Colors.MAGENTA}{'='*50}")
    print(f"{Colors.BOLD}🧠 THINKING PROCESS{Colors.END}")
    print(f"{Colors.MAGENTA}{'='*50}{Colors.END}")
    print(f"{Colors.CYAN}{content}{Colors.END}")
    print(f"{Colors.MAGENTA}{'='*50}{Colors.END}\n")

# For ToolMessage with better formatting
def print_tool_message(tool_msg):
    content = tool_msg.content if hasattr(tool_msg, 'content') else str(tool_msg)
    print(f"\n{Colors.YELLOW}{'─'*30}")
    print(f"{Colors.BOLD}🔧 TOOL OUTPUT{Colors.END}")
    print(f"{Colors.YELLOW}{'─'*30}{Colors.END}")
    print(f"{Colors.WHITE}{content}{Colors.END}")
    print(f"{Colors.YELLOW}{'─'*30}{Colors.END}\n")

# For final response with better formatting
def print_final_response(response_msg):
    content = response_msg.content if hasattr(response_msg, 'content') else str(response_msg)
    print(f"\n{Colors.GREEN}{'='*40}")
    print(f"{Colors.BOLD}📤 FINAL RESPONSE{Colors.END}")
    print(f"{Colors.GREEN}{'='*40}{Colors.END}")
    print(f"{Colors.CYAN}{content}{Colors.END}")
    print(f"{Colors.GREEN}{'='*40}{Colors.END}\n")
def logger_into_file(input_log,log_file_path: str):
    """Set up logging to a file"""
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    with open(log_file_path, 'a') as log_file:
        log_file.write(f"{input_log}\n")
    return
def truncate_log(log: str, max_length: int = 1000) -> str:
    """Truncate log to a maximum length"""
    if len(log) > max_length:
        return log[:max_length] + "...[truncated]"
    return log
class VMAgent:
    """LangGraph agent that can autonomously use VM tools"""
    
    def __init__(self, model: BaseChatModel):
        self.mcp = None
        self.prompt_dict = PromptDict()
        self.model_origin = model
        self.logger = AgentLogger()
        self.config = {
            "recursion_limit": 1000,
            "cache": False,
        }
        self.max_log = 3
        agent = StateGraph(AgentState)
        
        # Add nodes
        agent.add_node("init_state", self._init_state)
        agent.add_node("query_rag", self._query_rag)
        agent.add_node("summary_context", self._summary_rag)
        agent.add_node("planning_grand_execution", self._planning_grand_execution)
        agent.add_node("planning_execution", self._planning_execution)
        agent.add_node("tools_summarizer", self._tools_summarizer)
        agent.add_node("prepare_prompt", self._prepare_prompt)
        agent.add_node("tools", ToolNode(SLURM_TOOLS))
        agent.add_node("generate_answer", self.call_model)
        agent.add_node("generate_final", self.generate_final)
        agent.add_node("log_summarizer", self.log_summarizer)

        
        agent.add_edge("init_state", "planning_execution")
   
        agent.add_conditional_edges(
            "planning_execution",
            self._should_retrieval,
            {
                "call_rag": "query_rag",
                "continue": "prepare_prompt",
                "generate_final": "generate_final"
            }
        )
        agent.add_edge("query_rag", "planning_grand_execution")
        agent.add_edge("planning_grand_execution", "tools_summarizer")
        agent.add_edge("tools_summarizer", "planning_execution")
        agent.add_edge("prepare_prompt", "generate_answer")

 
        agent.add_edge("generate_answer", "tools")
        agent.add_edge("tools", "log_summarizer")
        agent.add_edge("log_summarizer", "tools_summarizer")
        agent.add_edge("tools_summarizer", "planning_execution")
        agent.add_edge("generate_final", END)
        
        agent.set_entry_point("init_state")
        self.graph = agent.compile(checkpointer=None, store=None)
    
    async def _init_state(self, state: AgentState) -> AgentState:
        agent = AgentState(
            agent_id = state.get("agent_id", "default-agent"),
            messages = state.get("messages", ""),
            context = state.get("context", ""),
            thinking = state.get("thinking", []),
            response = state.get("response", ""),
            task = state.get("task", "chat"),
            attempt= state.get("attempt", 1),
            use_vm = state.get("use_vm", False),
            cluster_ip = ENV_IP,
            env_port = ENV_PORT,
            env_working_dir = ENV_WORKING_DIR,
        )
        return agent
    def _should_replan(self, state: AgentState) -> str:
        """
        Decide what to do after tool execution:
        - "replan": Tool results indicate we need a new approach
        - "continue": Continue with current plan, just update prompt
        - "complete": Tool results are sufficient to generate final answer
        """
        # Example logic (customize based on your needs):
        
        # Check if the tool execution failed or returned unexpected results
        for message in state.get("messages", [])[::-1]:
            if isinstance(message, ToolMessage) and "error" in str(message).lower():
                return "replan"
        return "continue"


    def _should_continue(self, state: AgentState):
        """Decide whether to continue with tools or end"""
        last_message = state["messages"][-1]
        # If the last message has tool calls, execute them
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            return "tools"
        return "end"
    
    async def _query_rag(self, state: AgentState):
        thinking = state.get("thinking", [])

        try:
            agent_logger.info(f"Node: Query_Rag")
            agent_logger.info(f"Execute retrieval information...")
            
            async with aiohttp.ClientSession(CHROMA_HOST) as session:
                agent_logger.debug(f"Successful connect to {CHROMA_HOST}")

                messages = state.get("messages", [])
                messages = [message for message in messages if isinstance(message, (HumanMessage))]
                rag_prompt = self.prompt_dict.substitute('query_rag.txt',{
                    "thinking": thinking[-1].content if thinking else "",
                })
                langchain_messages = [
                    SystemMessage(content=rag_prompt),
                    *messages
                ]
                answer = await self.model_origin.ainvoke(langchain_messages,self.config)
                # print(f'relation_tag {relation_tag}')
                # relation_tag = await self.call_model(state)
                print(f'relation_tag {answer.content}')
                agent_logger.debug(f"Message to query: {state['messages']}")
                agent_logger.debug(f"Relation tag: {answer.content}")
                body = {
                    # "collection_name": "OpenWebUI_HTML",
                    # "collection_name": "BTL",
                    "collection_name": "WebUI_Markdown",
                    "query": answer.content,
                    "n_result": 5,
                }
                async with session.post("/query_collection", json=body) as responses:
                    responses = await responses.json()
                    responses = responses.get("result", [])
                    # agent_logger.debug(f"After calling retrieval tool: {responses}")
                    agent_logger.debug(f"After calling retrieval tool:\n{''.join([r.get('document', '') for r in responses])}")
                    context = []
                    for response in responses:
                        context.append(response.get("document", ""))
                    print(f'CONTEXT? {context}')
                    return {
                        # "messages": AIMessage(content="\n".join(f"RELEVANT CONTEXT POSITION {i + 1}\n{j}" for i, j in enumerate(context))),
                        "context": context,
                        "rag_query": state.get("rag_query", []) + [answer.content]
                    }
        except Exception as e:
            agent_logger.debug(f"Error querying RAG: {e}")
            raise e

    async def _summary_rag(self, state: AgentState):
        agent_logger.info("Node: summary_context")
        try:
            agent_logger.info(f"summary retrieval information...")
            prompt = self.prompt_dict.substitute('summary_rag.txt',{
                "retrieval_context": "\n".join(state["context"])
            }) 
            state['system_prompt'] = prompt
            agent_logger.debug(f"number of context: {len(state['context'])}")

            messages = state.get("messages", []) 
            messages = [message for message in messages if isinstance(message, (HumanMessage))]
            langchain_messages = [
                SystemMessage(content=state.get("system_prompt", "You are a helpful assistant.")),
                *messages
            ]
            contexts = await self.model_origin.ainvoke(langchain_messages,self.config)
            # print(f'contexts {contexts}')
            
            # contexts = await self.call_model(state)
            return {
                "context": contexts.content
            }
        except Exception as e:
            agent_logger.debug(f"Error summary context: {e}")
            raise e

    async def _tools_summarizer(self, state: AgentState):
        """Summarize ALL tool executions since the last planning cycle"""
        agent_logger.debug("Node: tools_summarizer")
        
        messages = state.get("messages", [])
        current_logs = state.get("summarized_logs", [])
        
        # Find all tool messages that haven't been summarized yet
        # We check from the last AIMessage (thinking) to find new tool executions
        new_tool_messages = []
        
        # Find the last thinking message index
        last_thinking_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], AIMessage) and not (hasattr(messages[i], 'tool_calls') and messages[i].tool_calls):
                # This is a thinking message (AIMessage without tool_calls)
                last_thinking_idx = i
                break
        
        # Collect all tool messages after the last thinking
        if last_thinking_idx >= 0:
            for i in range(last_thinking_idx + 1, len(messages)):
                if isinstance(messages[i], ToolMessage):
                    new_tool_messages.append(messages[i])
        else:
            # If no thinking found, get all tool messages
            new_tool_messages = [msg for msg in messages if isinstance(msg, ToolMessage)]
        
        if not new_tool_messages:
            agent_logger.debug("No new tool messages to summarize")
            return {"summarized_logs": current_logs}
        
        print(f"\n{'='*70}")
        print(f"SUMMARIZING {len(new_tool_messages)} TOOL EXECUTION(S)")
        print(f"{'='*70}\n")
        
        # Summarize each tool execution
        new_summaries = []
        
        for idx, tool_msg in enumerate(new_tool_messages, 1):
            tool_name = getattr(tool_msg, 'name', 'unknown_tool')
            tool_content = tool_msg.content
            
            tool_content_for_summary = tool_content
            
            # Create summarization prompt
            prompt = f"""Summarize this Slurm tool execution result concisely.

    Tool Name: {tool_name}

    Tool Output:
    {tool_content_for_summary}

    Provide a brief summary (2-4 sentences) including:
    - What the tool did
    - Key results (job IDs, partition names, states, node names, etc.)
    - Any errors or important status information

    Preserve exact values like job IDs, paths, partition names, and node names.

    Summary:"""
            
            try:
                # Use model without tool binding
                summary_model = self.model_origin.bind_tools([])
                
                response = await summary_model.ainvoke([
                    SystemMessage(content="You are a technical summarizer. Be concise but preserve critical details like IDs, names, paths, and status codes."),
                    HumanMessage(content=prompt)
                ], self.config)
                
                summary_text = response.content.strip()
                
                # Format summary
                timestamp = datetime.now(UTC).isoformat()
                formatted_summary = f"""Tool: {tool_name}
    Summary: {summary_text}
    Timestamp: {timestamp}"""
                
                new_summaries.append(formatted_summary)
                
                print(f"[{idx}/{len(new_tool_messages)}] Summarized: {tool_name}")
                print(f"    {summary_text}...")
                
            except Exception as e:
                agent_logger.error(f"Failed to summarize {tool_name}: {e}")
                
                # Fallback
                fallback = f"""Tool: {tool_name}
    Summary: [Summarization failed] Output: {tool_content}
    Timestamp: {datetime.now(UTC).isoformat()}"""
                
                new_summaries.append(fallback)
        
        print(f"\n{'='*70}")
        print(f"SUMMARIZATION COMPLETE: {len(new_summaries)} summaries added")
        print(f"{'='*70}\n")
        
        return {
            "summarized_tools": current_logs + new_summaries
        }
    async def _planning_grand_execution(self,state: AgentState):
        pass
    async def _planning_execution(self,state: AgentState):
        agent_logger.debug("Node: planning_execution")
        #get logs kwargs in the ToolMessage

        messages = state.get("messages", [])
        inverted_messages = messages[::-1]

        if inverted_messages[0] and isinstance(inverted_messages[0], ToolMessage):
            print_tool_message(inverted_messages[0])
        collected_logs = [str(msg) for msg in state.get('summarized_logs',[])]
        print(f'collected_logs {collected_logs if collected_logs else "No summarized logs"}')
        truncate_logs = [f"\nATTEMPT INDEX {i + 1}\n{log}\n" for i, log in enumerate(collected_logs)]
        logs = "\n".join(truncate_logs)
        context = state.get("context", [])
        contexts = "\n".join(f"\nRELEVANT CONTEXT POSITION {i + 1}\n{j}\n" for i, j in enumerate(context))
        rag_logs = state.get("rag_query", [])
        rag_logs = "\n".join(f"\nRAG QUERY INDEX {i + 1}\n{j}\n" for i, j in enumerate(rag_logs[-100:]))
        substitution_data = {
            "given_context": contexts,
            "extracted_logs": logs,
            "rag_querys": rag_logs,
            "logs_count": len(collected_logs),
            "rag_count": len(state.get("rag_query", [])),
            "summarized_tools": "\n".join(state.get("summarized_tools", [])),
        }
    
        prompt = self.prompt_dict.substitute('planning_execution.txt',substitution_data)
        state['system_prompt'] = prompt
        messages = state.get("messages", []) 
        human_messages = [message for message in messages if isinstance(message, (HumanMessage))]
        langchain_messages = [
            *human_messages,
            # *messages[-self.max_log:],
            SystemMessage(content=state.get("system_prompt", "You are a helpful assistant.")),
        ]
        # answer = await self.model_origin.ainvoke(langchain_messages,self.config)
        index = 0
        planning_model = self.model_origin.bind_tools([])
        while True:
            # answer = await self.model_origin.ainvoke(langchain_messages,self.config)
            if index > 0:
                langchain_messages.insert(0, SystemMessage(content="""
YOU NEED TO RESPONSE WITH THIS FORMAT, MAKE SURE TO INCLUDE ALL SECTIONS:
**SITUATION:**  
...
**LAST TOOL:**  
...


**ATTEMPTS:**  
...

**WHAT YOU HAVE:**  
...

**NEXT STEP:**  
...

**HOW TO DO IT:**  
...

**WHAT TO EXPECT:**  
...
                                                           
"""))
            answer = await planning_model.ainvoke(langchain_messages,self.config)
            import re
            # pattern = re.compile(r"situation\s*analysis", re.IGNORECASE)
            if  answer.content!="" :
                break

            # if answer.content != "":
            #     break
            index += 1
            print(f"Response missing required sections, retrying...{answer}")
        import re
        print_thinking(answer)
        print(f'Planning output: {type(answer)}')
        # def sanitize_pattern(pattern):
        #     # Escape special characters except for valid wildcard symbols
        #     return re.sub(r"([.$^|+()\\])", r"\\\1", pattern)

        # # Example usage
        # sanitized_pattern = sanitize_pattern(answer.content)
        # print(f'answer {sanitized_pattern}')
        
        # agent_logger.debug(f"list of actions:\n{sanitized_pattern}")
        return {
            "thinking": state.get("thinking", []) + [answer],
        }
    async def _should_retrieval(self, state: AgentState):
        """Route to appropriate next step based on strategic planning output"""
        
        routing_prompt = """
        You are a ROUTING DECISION AGENT. Your job is to determine the next step in the execution pipeline based on the strategic planning output.

        Analyze the strategic plan and route to the appropriate next action:

        CURRENT STATE:
        - Strategic Plan: {planning_output}

        ROUTING RULES - Analyze the **NEXT ACTION** section of the Strategic Plan:

        1. Route to "RAG_NEEDED" if:
        - NEXT ACTION contains "Search RAG for" 
        - NEXT ACTION mentions "RAG", "search", "documentation", or "lookup"
        - Agent requests knowledge retrieval or information gathering

        2. Route to "EXECUTE_TOOLS" if:
        - NEXT ACTION contains "Execute" followed by specific tool/command
        - NEXT ACTION mentions specific actions like "curl", "shell", "API call"
        - Agent provides concrete implementation steps in SPECIFIC GUIDANCE
        - Ready for direct execution with available parameters

        3. Route to "GENERATE_FINAL" if:
        - NEXT ACTION contains "Generate final answer"
        - NEXT ACTION indicates task completion or termination
        - SPECIFIC GUIDANCE contains summary or completion status
        - Agent declares task finished or cannot continue

        DECISION PRIORITY (check in this order):
        1. First check for "Generate final answer" → GENERATE_FINAL
        2. Then check for "Search RAG" or knowledge requests → RAG_NEEDED  
        3. Finally check for "Execute" or implementation steps → EXECUTE_TOOLS

        FAILURE CONDITIONS (route to GENERATE_FINAL):
        - No clear NEXT ACTION identified
        - Contradictory or unclear instructions
        - Multiple conflicting actions specified

        IF THE PLAN IS EMPTY OR UNREADABLE, DEFAULT TO CONTINUE (EXECUTE_TOOLS).
        OUTPUT FORMAT - Return exactly one of these strings:
        RAG_NEEDED
        EXECUTE_TOOLS
        GENERATE_FINAL

        Analyze the strategic plan and make your routing decision:
        """
        
        messages = state.get("messages", [])
        planning_output = state.get("thinking", [])
        if planning_output != []:
            if planning_output[-1].content != '':
                planning_output = planning_output[-1].content
            else: 
                return "continue"
        else:
            planning_output = ""
        
        formatted_prompt = routing_prompt.format(
            planning_output=planning_output,
        )
        
        langchain_messages = [formatted_prompt]
        answer = await self.model_origin.ainvoke(langchain_messages, self.config)
        
        # Parse the response and return routing decision
        response = answer.content.strip()
        
        if "RAG_NEEDED" in response:
            print(f"Routing decision: {response}")
            print(f"Route: RAG_NEEDED - Retrieving knowledge")
            return "call_rag"
        elif "EXECUTE_TOOLS" in response:
            print(f"Routing decision: {response}")
            print(f"Route: EXECUTE_TOOLS - Proceeding to tool execution")
            return "continue"
        elif "GENERATE_FINAL" in response:
            print(f"Routing decision: {response}")
            print(f"Route: GENERATE_FINAL - Generating final answer")
            return "generate_final"
        else:
            # Fallback for unclear responses
            print(f"Routing decision unclear: {response}")
            print(f"Route: GENERATE_FINAL - Fallback due to unclear routing")
            return "continue"

    async def _prepare_prompt(self, state: AgentState):
        # self.model = self.model_origin.bind_tools(SLURM_TOOLS)
        try:
            agent_logger.debug("Node: calling_tools")
            print("Node: calling_tools")
            thinking = state.get("thinking", [])
            print(f'thinking {thinking[-1]}')
            print(f'thinking type {type(thinking[-1])}')
            if thinking:
                thinking = thinking[-1]
            # collected_logs = [str({'content': msg.content,
                    # 'name': msg.name}) for msg in state['messages'] if isinstance(msg, ToolMessage)]
            collected_logs = [str(msg) for msg in state.get('summarized_logs',[])]
            
            collected_logs = collected_logs[-self.max_log:]
            truncate_logs = [log for log in collected_logs]
            logs = "\n".join(f"ATTEMPT {i + 1}\n{log}" for i, log in enumerate(truncate_logs))

            prompt = self.prompt_dict.substitute('prepare_prompt.txt',{
                "thinking": thinking,
                "logs": logs,
            })
            state['system_prompt'] = prompt
            cluster_ip = await self.register_vm(state=state)

            print(f"Connecting to VM at {cluster_ip}")
            # langchain_messages = [
            #     SystemMessage(content=state.get("system_prompt", "You are a helpful assistant.")),
            #     *state.get("messages", [])
            # ]
            # answer = await self.model_origin.ainvoke(langchain_messages,self.config)
            # print(f"Connecting to VM at {cluster_ip}")

            # agent_logger.debug(f"tool callings: {answer}")
            # print(f"tool callings: {answer}")
            return {
                "system_prompt": state['system_prompt'],
                "attempt": state.get("attempt", 0) + 1,
                "cluster_ip": cluster_ip,
                "cluster_port": state.get("cluster_port", ENV_PORT),
            }
        except Exception as e:
            print(e)
            raise e

    async def generate_answer_exclusive(self, user_input: List[Dict[str, Any]], thread_id: str) -> Dict[str, Any]:
        langchain_messages = [
            *user_input
        ]
        answer = await self.model_origin.ainvoke(langchain_messages, self.config)
        return {
            "content": answer.content
        }
    async def generate_final(self, state: AgentState) -> Dict[str, Any]:
        messages = state.get("messages", [])
        logs = [msg for msg in state.get("messages", []) if isinstance(msg, ToolMessage)]
        logs = "\n".join(f"ATTEMPT INDEX {i + 1}\n{j}" for i, j in enumerate(logs))
        final_prompt = self.prompt_dict.substitute('final.txt',{
            "given_context": state.get("context", ""),
            # "logs": logs,
            "thinking": "\n".join(f"THINKING SESSION {i + 1}\n{j}" for i, j in enumerate(state.get("thinking", []))),
        })
        human_messages = [mess for mess in state.get("messages", []) if isinstance(mess, HumanMessage)]
        langchain_messages = [
            SystemMessage(content=final_prompt),
            *messages 
        ]
        answer = await self.model_origin.ainvoke(langchain_messages, self.config)
        return {
            "final_response": answer
        }
    async def log_summarizer(self, state: AgentState) -> dict:
        FINAL_OUTPUT_PROCESSING_PROMPT = """
Extract ONLY the important fields that were requested in the plan. Return exact values with no modifications.

Rules:
1. Find what was requested in the planning phase
2. Extract EXACT values from execution logs for those requests only
3. No summaries, no explanations, no extra text
4. If value not found, write "NOT_FOUND"
5. Keep original formatting and characters
6. VALIDATE that extracted values are correct and complete, ask yourself "Did I got every value exactly as requested?", "Did i miss anything?","Did i got the important token, names,...?"

HAVE YOU FOLLOWED SUCCESS CRITERIA??

Output format:
FIELD_NAME: exact_value
FIELD_NAME: exact_value
STATUS: exact_value
ERROR: exact_value OR "NOT_FOUND"
    <thinking>
    {thinking}
    </thinking>

    <logs>
    {logs}
    </logs>
    """
        
        # Get the last ToolMessage
        messages = state.get("messages", [])
        last_tool_msg = None
        last_tool_index = -1
        
        # Find the last ToolMessage
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], ToolMessage):
                last_tool_msg = messages[i]
                last_tool_index = i
                break
        
        if last_tool_msg is None:
            return {"summarized_logs": state.get("summarized_logs", [])}
        
        # Create the prompt
        prompt = FINAL_OUTPUT_PROCESSING_PROMPT.format(
            thinking=state.get("thinking", [])[-1] if state.get("thinking", []) else "",
            logs=last_tool_msg.content,
        )
        
        # Get summarized content
        langchain_messages = [SystemMessage(content=prompt)]
        answer = await self.model_origin.ainvoke(langchain_messages, self.config)
        summarized_content = answer.content
        
        # # METHOD 1: Create new ToolMessage with same tool_call_id but summarized content
        # new_tool_message = ToolMessage(
        #     content=summarized_content,
        #     tool_call_id=last_tool_msg.tool_call_id,
        #     name=getattr(last_tool_msg, 'name', None)
        # )
        
        # # Replace the last ToolMessage in messages
        # new_messages = messages[:last_tool_index] + [new_tool_message] + messages[last_tool_index + 1:]
        
        return {
            "summarized_logs": state.get("summarized_logs", []) + [summarized_content]
        }
    async def call_model(self, state: AgentState) -> Dict[str, List[AIMessage]]:
        messages = state.get("messages", [])

        # print(f"System prompt: {state.get('system_prompt', '')}")
        print(f"Calling model with {len(messages)} messages")

    
        # print('call model node')
        messages = state.get("messages", []) 
        messages = [message for message in messages if isinstance(message, (HumanMessage))]
        langchain_messages = [
            SystemMessage(content=state.get("system_prompt", "You are a helpful assistant.")),
            *messages
        ]
        from copy import deepcopy
        from langchain_core.runnables import RunnableLambda

        def create_vm_injector(cluster_ip, cluster_port):
            def inject_vm_args(ai_msg):
                if not hasattr(ai_msg, 'tool_calls') or not ai_msg.tool_calls:
                    return ai_msg
                    
                # Modify the tool calls in place or create a copy
                for tool_call in ai_msg.tool_calls:
                    tool_call["args"]["cluster_ip"] = cluster_ip
                    tool_call["args"]["cluster_port"] = cluster_port
                return ai_msg
            
            return RunnableLambda(inject_vm_args)

        vm_injector = create_vm_injector(state["cluster_ip"], state.get('cluster_port', ENV_PORT))
        model = self.model_origin
        chain = model.bind_tools(SLURM_TOOLS) | vm_injector
        print('generating call tools')
        response = await chain.ainvoke(langchain_messages,self.config)
        # response = await self.model.ainvoke(langchain_messages)
        
        # Handle last step constraint
        # if state.is_last_step and response.tool_calls:
        #     return {
        #         "messages": [
        #             AIMessage(
        #                 id=response.id,
        #                 content="I need more steps to complete this task properly.",
        #             )
        #         ]
        #     }
        # print(f"Model response: {response}")
        
        # if response.tool_calls:
            # print_tool_message(response.tool_calls)
        print(f"Model response received. Tool calls: {len(response.tool_calls) if hasattr(response, 'tool_calls') else 0}")
        print(response.tool_calls)
        return {"messages": [response]}
    
    async def register_vm(self, state: AgentState):
        if state['use_vm'] == False:
            cluster_ip = ENV_IP
            return cluster_ip
        if state.get('cluster_ip', True):
            async with aiohttp.ClientSession(f"{MULTIPASS_URL}") as get_vm:
                res = await get_vm.get(url=f"get_free_assigned_vm/{state['agent_id']}")
                res = await res.json()
                if not res.get("data", []):
                    async with aiohttp.ClientSession(f"{MULTIPASS_URL}") as session:
                        request_body = {
                            "agent_id": state['agent_id'],
                            "cpu": 1,
                            "memory": "1G",
                            "disk": "5G",
                            "cloud_init": VM_CLOUD_INIT_PATH,
                            "priority": 0,
                            "enable_cloning": True
                        }
                        request = await session.post(url=f"request_vm", json=request_body)
                        if request.status != 200:
                            agent_logger.error(f"Failed to request VM: {request.status}")
                            return
                        else:
                            res = await get_vm.get(url=f"get_free_assigned_vm/{state['agent_id']}")
                            res = await res.json()
                
                vm_name= res['data'][0]['vm_name']
                cluster_ip = res['data'][0]['info']['info']['info'][f'{vm_name}']['ipv4'][0]
                return cluster_ip

    async def run(self, user_input: List[Dict[str, Any]], thread_id: str) -> Dict[str, Any]:
        messages = []
        for m in user_input:
            if m['role'] == 'user':
                messages.append(HumanMessage(content=m['content']))
            elif m['role'] == 'system':
                messages.append(SystemMessage(content=m['content']))
            elif m['role'] == 'tool':
                messages.append(ToolMessage(content=m['content'], name=m.get('name', 'tool')))
            elif m['role'] == 'assistant':
                messages.append(AIMessage(content=m['content']))
        initial_state = AgentState(
            messages=messages,
            agent_id=thread_id,
        )
        """Execute task with comprehensive logging"""
        task_id = str(uuid.uuid4())
        start_time = time_module.time()
        
        try:
            result = await self.graph.ainvoke(initial_state,self.config)
            final_response = result["messages"][-1].content
            def extract_situation_analysis(planning_output):
                """Extract the SITUATION ANALYSIS section from planning agent output."""
                try:
                    after_header = planning_output.split('**SITUATION ANALYSIS:**')[1]
                    content = after_header.split('**')[0]
                    return content.strip()
                except Exception as e:
                    return ""
            return {
                "content":result["messages"][-1].content,
                "thinking": (
                    "\n".join(
                        [
                            f"**THINKING SESSION** {i + 1}\n_{extract_situation_analysis(t.content)}_"
                            for i, t in enumerate(result["thinking"])
                            if t and hasattr(t, "content") and extract_situation_analysis(t.content) !="" 
                        ]
                    )
                    if result.get("thinking") else ""
                ),
                "tool_calls": [m for m in result["messages"] if isinstance(m, ToolMessage) and m],
            }
            
        except Exception as e:
            error_time = int((time_module.time() - start_time) * 1000)
            error_msg = f"Execution failed: {str(e)}"
            # print(error_msg)
            # Log the error as a failed tool execution
            try:
                if hasattr(self, 'logger') and self.logger.current_step:
                    self.logger.log_tool_execution(
                        tool_name="system_error",
                        inputs={"operation": "run_with_logging"},
                        outputs={"error": str(e)},
                        success=False,
                        execution_time_ms=error_time,
                        error=str(e)
                    )
                    self.logger.end_step("Task execution failed with error", False)
            except:
                pass  # Don't let logging errors mask the original error
            
            # End task logging
            try:
                if hasattr(self, 'logger'):
                    self.logger.end_task(
                        error_msg, 
                        False, 
                        [f"System error: {str(e)}", f"Error type: {type(e).__name__}"]
                    )
            except:
                pass
                
            # print(f"Task {task_id} failed after {error_time}ms: {error_msg}")
            
            return {
                "success": False,
                "error": str(e),
                "task_id": task_id,
                "execution_time_ms": error_time
            }

    def _extract_lessons_from_execution(self, result: Dict[str, Any], success: bool, execution_time_ms: int) -> list:
        """Extract lessons learned from task execution"""
        lessons = []
        
        try:
            # Basic performance lesson
            if execution_time_ms > 30000:  # > 30 seconds
                lessons.append(f"Task took {execution_time_ms}ms - consider optimization")
            elif execution_time_ms < 5000:  # < 5 seconds
                lessons.append("Task completed quickly - efficient execution")
            
            # Success/failure analysis
            if success:
                lessons.append("Task completed successfully")
                if result.get("messages"):
                    message_count = len(result["messages"])
                    if message_count > 5:
                        lessons.append(f"Generated {message_count} messages - possibly complex task")
                    elif message_count == 1:
                        lessons.append("Single response - straightforward task")
            else:
                lessons.append("Task failed - review error patterns")
            
            # Analyze response content if available
            if result.get("messages"):
                final_message = result["messages"][-1]
                if hasattr(final_message, 'content'):
                    content = final_message.content.lower()
                    if "successfully" in content:
                        lessons.append("Response indicates successful operation")
                    if "error" in content or "failed" in content:
                        lessons.append("Response contains error indicators")
                    if "timeout" in content:
                        lessons.append("Possible timeout issue detected")
            
            # VM-specific lessons
            if hasattr(self, 'mcp') and self.mcp:
                lessons.append(f"Used VM connection to {getattr(self.mcp, 'cluster_ip', 'unknown')}")
        
        except Exception as e:
            lessons.append(f"Failed to extract lessons: {str(e)}")
        
        return lessons

    # Additional helper method for monitoring recent executions
    def get_recent_execution_logs(self, hours_back: int = 1) -> Dict[str, Any]:
        """Get recent execution logs for monitoring and debugging"""
        if not hasattr(self, 'logger'):
            return {"error": "Logger not initialized"}
        
        try:
            recent_logs = self.logger.get_logs_by_time(hours_back)
            
            # Add some basic statistics
            logs = recent_logs.get("logs", [])
            success_count = sum(1 for log in logs if log.get("success", False))
            total_count = len(logs)
            
            return {
                "time_range": f"Last {hours_back} hour(s)",
                "total_executions": total_count,
                "successful_executions": success_count,
                "success_rate": success_count / total_count if total_count > 0 else 0,
                "logs": logs,
                "tool_stats": self.logger._get_tool_stats()
            }
        except Exception as e:
            return {"error": f"Failed to get execution logs: {str(e)}"}

    def get_current_task_status(self) -> Dict[str, Any]:
        """Get status of currently executing task"""
        if not hasattr(self, 'logger'):
            return {"error": "Logger not initialized"}
        
        try:
            current_task = self.logger.current_task
            current_step = self.logger.current_step
            
            if not current_task:
                return {"status": "idle", "message": "No active task"}
            
            return {
                "status": "active",
                "task_id": current_task.task_id,
                "request": current_task.original_request,
                "current_step": current_step.step_number if current_step else None,
                "steps_completed": len(current_task.steps),
                "tools_executed": len(current_task.tool_executions),
                "start_time": current_task.timestamp
            }
        except Exception as e:
            return {"error": f"Failed to get task status: {str(e)}"}
        
from langchain_ollama import ChatOllama

async def main(input_messages):
    model = ChatOllama(
        model=OLLAMA_MODEL,
        base_url=BASE_OLLAMA_URL,
        # Ultra-strict settings:
        temperature=0.0,
        top_k=1,
        top_p=0.01,
        # Format enforcement:
        mirostat=2,
        mirostat_eta=0.01,
        mirostat_tau=1.0,
        # Critical for format following:
        repeat_last_n=128,        # Look back further for patterns
        repeat_penalty=1.0,       # Don't penalize format repetition
        presence_penalty=0.0,     # Don't discourage format words
        frequency_penalty=0.0,    # Don't discourage format structure
        cache=False,
        streaming=False,
    )
    agent = VMAgent(model)
    initial_state = AgentState(
        messages=[HumanMessage(content=input_messages['content'])],
        agent_id="default-agent",
    )
    agent_logger.debug(f"run agent with state: {initial_state}")
    result = await agent.run(user_input=[input_messages], thread_id="default-agent")
    return result

if __name__ == "__main__":
    import asyncio
    user_input = {"role": "user","content": """In openwebui web application, there is user and group, i want you to add an user loitr to a modder group."""}

    response = asyncio.run(main(user_input))
    print(f"{Colors.GREEN}📤 Response: {Colors.END}{Colors.CYAN}{response}{Colors.END}")

from fastapi.responses import StreamingResponse
from typing import AsyncGenerator
from fastapi import Request
async def generate_vm_agent_streaming_completion(user_input, thread_id):
    """
    Stream VMAgent execution focusing on thinking, tool calls, and RAG queries
    """
    
    async def focused_vm_stream():
        try:
            # Initialize VMAgent
            from langchain_ollama import ChatOllama
            
            model = ChatOllama(
                model=OLLAMA_MODEL,
                base_url=BASE_OLLAMA_URL,
                # Ultra-strict settings:
                temperature=0.0,
                top_k=1,
                top_p=0.01,
                # Format enforcement:
                mirostat=2,
                mirostat_eta=0.01,
                mirostat_tau=1.0,
                # Critical for format following:
                repeat_last_n=128,        # Look back further for patterns
                repeat_penalty=1.0,       # Don't penalize format repetition
                presence_penalty=0.0,     # Don't discourage format words
                frequency_penalty=0.0,    # Don't discourage format structure
                cache=False,
                streaming=False,
            )
            
            agent = VMAgent(model)
            
            # Convert user_input to proper format
            langchain_messages = []
            for msg in user_input:
                if msg['role'] == 'user':
                    langchain_messages.append(HumanMessage(content=msg['content']))
                elif msg['role'] == 'system':
                    langchain_messages.append(SystemMessage(content=msg['content']))
                elif msg['role'] == 'assistant':
                    langchain_messages.append(AIMessage(content=msg['content']))
            
            initial_state = {
                "messages": langchain_messages,
                "agent_id": thread_id,
                "context": [],
                "thinking": [],
                "response": "",
                "task": "chat", 
                "attempt": 1,
                "results_tool_calls": [],
                "logs": [],
                "log_file_paths": set(),
                "rag_query": [],
                "summarized_logs": [],
                "cluster_ip": None,
                "cluster_port": ENV_PORT,
                "system_prompt": ""
            }
            
            # Track previous state to detect changes
            prev_thinking_count = 0
            prev_rag_count = 0
            prev_tool_count = 0
            
            # Stream using LangGraph's astream
            async for event in agent.graph.astream(initial_state, agent.config):
                for node_name, node_result in event.items():
                    
                    # Stream thinking updates
                    if "thinking" in node_result and node_result["thinking"]:
                        current_thinking_count = len(node_result["thinking"])
                        if current_thinking_count > prev_thinking_count:
                            # New thinking added
                            latest_thinking = node_result["thinking"][-1]
                            if hasattr(latest_thinking, 'content'):
                                thinking_content = latest_thinking.content
                                
                                # Extract key sections
                                # situation = extract_section(thinking_content, "SITUATION ANALYSIS")
                                # next_action = extract_section(thinking_content, "NEXT ACTION")
                                # guidance = extract_section(thinking_content, "SPECIFIC GUIDANCE")

                                # Create highlighted, readable thinking display
                                content_parts = []
                                content_parts.append(f"***╔══════════════════════════════════════╗")
                                content_parts.append(f"║            THINKING SESSION {current_thinking_count}         ║")
                                content_parts.append(f"╚══════════════════════════════════════╝***")
                                content_parts.append("")
                                
                                # if situation != "Not found":
                                #     content_parts.append("🔍 **SITUATION ANALYSIS:**")
                                #     # content_parts.append("━" * 40)
                                #     content_parts.append(f"{situation}")
                                #     content_parts.append("")
                                
                                # if next_action != "Not found":
                                #     content_parts.append("🎯 **NEXT ACTION:**")
                                #     # content_parts.append("━" * 40)
                                #     content_parts.append(f"{next_action}")
                                #     content_parts.append("")
                                
                                # if guidance != "Not found":
                                #     content_parts.append("📋 **SPECIFIC GUIDANCE:**")
                                #     # content_parts.append("━" * 40)
                                #     content_parts.append(f"{str(guidance)}")
                                #     content_parts.append("")
                                
                                # if situation == "Not found" and next_action == "Not found" and guidance == "Not found":
                                    # If no sections found, just show full content
                                # thinking_content = extract_any_section(thinking_content)
                                content_parts.append(thinking_content)
                                content_parts.append("")

                                content_parts.append("─" * 50)
                                content_parts.append("")
                                
                                chunk = {
                                    "id": f"thinking-{current_thinking_count}",
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": "tma_agent_007",
                                    "choices": [{
                                        "index": 0,
                                        "delta": {
                                            "role": "assistant",
                                            "content": "\n".join(content_parts)
                                        },
                                        "finish_reason": None
                                    }]
                                }
                                yield f"data: {json.dumps(chunk)}\n\n"
                                prev_thinking_count = current_thinking_count
                    
                    # Stream RAG query updates
                    if "rag_query" in node_result and node_result["rag_query"]:
                        current_rag_count = len(node_result["rag_query"])
                        if current_rag_count > prev_rag_count:
                            latest_rag = node_result["rag_query"][-1]
                            
                            rag_content = []
                            rag_content.append("***┌─ 🔍 KNOWLEDGE SEARCH ─────────────────┐")
                            rag_content.append(f"│  Query #{current_rag_count}")
                            rag_content.append("└──────────────────────────────────────┘***")
                            rag_content.append("")
                            rag_content.append("🔎 **SEARCHING FOR:**")
                            rag_content.append(f"   {latest_rag}")
                            rag_content.append("")
                            rag_content.append("🔄 Retrieving relevant documents...")
                            rag_content.append("")
                            
                            chunk = {
                                "id": f"rag-{current_rag_count}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": "tma_agent_007",
                                "choices": [{
                                    "index": 0,
                                    "delta": {
                                        "role": "assistant",
                                        "content": "\n".join(rag_content)
                                    },
                                    "finish_reason": None
                                }]
                            }
                            yield f"data: {json.dumps(chunk)}\n\n"
                            prev_rag_count = current_rag_count
                    
                    # Stream tool calls
                    if "messages" in node_result and node_result["messages"]:
                        print(f"Detected {node_result['messages']} messages so far")
                        tool_messages = [msg for msg in node_result["messages"] if isinstance(msg, ToolMessage)]
                        current_tool_count = len(tool_messages)
                        print(f"Detected {current_tool_count} tool messages so far")
                        if current_tool_count > 0:
                            # New tool message
                            latest_tool = tool_messages[-1]
                            tool_name = getattr(latest_tool, 'name', 'unknown_tool')
                            tool_output = latest_tool.content
                            
                       
                            display_output = tool_output
                            
                            tool_content = []
                            tool_content.append("***┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓")
                            tool_content.append(f"┃        🔧 TOOL EXECUTION OUTPUT        ┃")
                            tool_content.append("┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛***")
                            tool_content.append("")
                            tool_content.append(f"⚡ **TOOL:** `{tool_name}`")
                            tool_content.append("")
                            tool_content.append("📤 **OUTPUT:**")
                            tool_content.append("```")
                            # Add line numbers for better readability if output has multiple lines
                            lines = display_output.split('\n')
                            # if len(lines) > 1:
                            #     for i, line in enumerate(lines[:10], 1):  # Show max 10 lines
                            #         tool_content.append(f"{i:2}: {line}")
                            #     if len(lines) > 10:
                            #         tool_content.append("... [more lines truncated] ...")
                            # else:
                            tool_content.extend(lines)
                            tool_content.append("```")
                            tool_content.append("")
                            tool_content.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                            tool_content.append("")
                            
                            chunk = {
                                "id": f"tool-{current_tool_count}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": "tma_agent_007",
                                "choices": [{
                                    "index": 0,
                                    "delta": {
                                        "role": "assistant",
                                        "content": "\n".join(tool_content)
                                    },
                                    "finish_reason": None
                                }]
                            }
                            yield f"data: {json.dumps(chunk)}\n\n"
                            prev_tool_count = current_tool_count
            
                    if node_name == "generate_final":
                        try:  
                            if node_result.get("final_response"):
                                # Add a clear header for final response
                                final_header = []
                                final_header.append("***╔════════════════════════════════════════════════════╗")
                                final_header.append("║                  📝 FINAL RESPONSE                 ║")
                                final_header.append("╚════════════════════════════════════════════════════╝***")
                                final_header.append("")
                                
                                # header_chunk = {
                                #     "id": "final-header",
                                #     "object": "chat.completion.chunk",
                                #     "created": int(time.time()),
                                #     "model": "tma_agent_007",
                                #     "choices": [{
                                #         "index": 0,
                                #         "delta": {"content": "\n".join(final_header)},
                                #         "finish_reason": None
                                #     }]
                                # }
                                # yield f"data: {json.dumps(header_chunk)}\n\n"
                                
                                # # Stream final response word by word for nice effect
                                # words = node_result.get("final_response", {}).content
                                # for i, word in enumerate(words):
                                #     chunk = {
                                #         "id": f"final-{i}",
                                #         "object": "chat.completion.chunk",
                                #         "created": int(time.time()),
                                #         "model": "tma_agent_007",
                                #         "choices": [{
                                #             "index": 0,
                                #             "delta": {"content": f"{word} "},
                                #             "finish_reason": None
                                #         }]
                                #     }
                                #     yield f"data: {json.dumps(chunk)}\n\n"
                                #     await asyncio.sleep(0.02)
                                
                                # # Add closing line
                                # footer_chunk = {
                                #     "id": "final-footer",
                                #     "object": "chat.completion.chunk", 
                                #     "created": int(time.time()),
                                #     "model": "tma_agent_007",
                                #     "choices": [{
                                #         "index": 0,
                                #         "delta": {"content": "\n\n" + "─" * 54 + "\n"},
                                #         "finish_reason": None
                                #     }]
                                # }
                                # yield f"data: {json.dumps(footer_chunk)}\n\n"
                                #simply output the final response at once
                                final_chunk = {
                                    "id": "final-response",
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": "tma_agent_007",
                                    "choices": [{
                                        "index": 0,
                                        "delta": {
                                            "role": "assistant",
                                            "content": "\n".join(final_header) + node_result.get("final_response", {}).content + "\n\n" + "─" * 54 + "\n"
                                        },
                                        "finish_reason": "stop"
                                    }]
                                }
                                yield f"data: {json.dumps(final_chunk)}\n\n"
                        except Exception as final_error:
                            print(f"Error getting final result: {final_error}")
                            # Continue without final result
            
            # Completion chunk
            completion_chunk = {
                "id": "completion",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "tma_agent_007",
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop"
                }]
            }
            yield f"data: {json.dumps(completion_chunk)}\n\n"
            
        except Exception as e:
            print(f"Error in focused_vm_stream: {e}")
            error_chunk = {
                "id": "error",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "tma_agent_007",
                "choices": [{
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "content": f"Error: {str(e)}"
                    },
                    "finish_reason": "stop"
                }]
            }
            yield f"data: {json.dumps(error_chunk)}\n\n"
    
    return StreamingResponse(
        focused_vm_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

def extract_section(text: str, section_name: str) -> str:
    """Extract a section from the thinking process"""
    try:
        start_marker = f"**{section_name}:**"
        start_idx = text.find(start_marker)
        if start_idx == -1:
            return "Not found"
        
        start_idx += len(start_marker)
        end_idx = text.find("**", start_idx)
        if end_idx == -1:
            end_idx = len(text)
        
        return text[start_idx:end_idx].strip()
    except:
        return "Error extracting"


def extract_any_section(text: str) -> str:
    """Extract the content of the first section from the thinking process"""
    try:
        start_marker = "**"
        start_idx = text.find(start_marker)
        if start_idx == -1:
            return "Not found"
        
        # Find the end of the section name (after the colon)
        name_end_idx = text.find("**", start_idx + len(start_marker))
        if name_end_idx == -1:
            return "Not found"
        
        # Find the colon after the section name
        colon_idx = text.find(":", start_idx + len(start_marker), name_end_idx)
        if colon_idx == -1:
            return "Not found"
        
        # Start of content is after the colon and space
        content_start = colon_idx + 1
        # Find the next section marker or end of text
        next_section_idx = text.find("**", name_end_idx + len(start_marker))
        if next_section_idx == -1:
            next_section_idx = len(text)
        
        return text[content_start:next_section_idx].strip()
    except:
        return "Error extracting"