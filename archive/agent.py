import os
from langchain_ollama import OllamaLLM
from langchain.schema import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import StateGraph, END, START

import asyncio
from typing import Dict, Any, List, Optional, TypedDict, Annotated,Union
import aiohttp
import logging
from utils import extract_context_summary_response, extract_tool_calls_from_xml
from google import genai
from tools import MCPConnection
client = genai.Client(api_key="API_PLACE_HOLDER")

agent_logger = logging.Logger(name="Agent 007")
agent_logger.setLevel(logging.DEBUG)
LOG_DIR = "/home/danhvuive/vm_logs"
# Add a console handler if not already present
if not agent_logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    agent_logger.addHandler(console_handler)

__all__ = ["run_agent", "Agent"]

BASE_OLLAMA_URL = "http://localhost:11434"
# OLLAMA_MODEL = "llama3.2"
# OLLAMA_MODEL = "gemma:7b"
OLLAMA_MODEL = "gpt-oss:latest"
GEMINI_MODEL = "gemini-2.5-flash"
_rag_server_port = "12000"
CHROMA_HOST = f"http://10.0.0.1:{_rag_server_port}"
VM_CLOUD_INIT_PATH = "/home/danhvuive/image-init.yaml"
VM_PORT = "http://10.29.12.9:8000"
llm = OllamaLLM(
    base_url=BASE_OLLAMA_URL, 
    model=OLLAMA_MODEL,
    temperature=0.0
    )

MULTIPASS_URL = f"http://10.0.0.01:8010/"

USING_GEMINI=False
async def get_response(prompt: str) -> str:
    if USING_GEMINI:
        response = client.models.generate_content(
            model=GEMINI_MODEL, contents=prompt
        )
        print(f"Response from Gemini: {response.text}")
        return response.text
    return await asyncio.get_event_loop().run_in_executor(None, llm.invoke, prompt)
    
#region Agent
class AgentState(TypedDict):
    agent_id: str
    vm_name: Optional[str]  # VM name assigned to the agent
    chat_history: Annotated[List[str], "The messages in the conversation"]
    context: Annotated[List[str], "The context query for the conversation use for context agent"]
    thinking: Annotated[List[str], "The thinking process in the conversation for action agent"]
    response: str
    results_tool_calls: Annotated[List[Dict[str, Any]], "The results of the tool calls"]
    task: Annotated[str, "for openweubui structure"]
    logs: Annotated[List[Union[str, Dict[str, Any]]], "The logs collected from the VM"]
    attempt: Annotated[int, "The current attempt number"]
    repo_name: Annotated[str, "The name of the repository being worked on"]
    log_file_paths: Annotated[set[str], "The set of log file paths"]
agent = StateGraph(AgentState)

def _init_state(state: AgentState):
    return AgentState(
        agent_id = state.get("agent_id", "default-agent"),
        chat_history = state.get("chat_history", []),
        context = state.get("context", []),
        thinking = state.get("thinking", []),
        response = state.get("response", ""),
        task = state.get("task", "chat"),
        attempt= state.get("attempt", 1),
        repo_name = state.get("repo_name", "openwebui")
    )

async def _query_rag(state: AgentState):
    try:
        agent_logger.info(f"Node: Query_Rag")
        agent_logger.info(f"Execute retrieval information...")
        async with aiohttp.ClientSession(CHROMA_HOST) as session:
            agent_logger.debug(f"Successful connect to {CHROMA_HOST}")
            message = state["chat_history"][-1] # last message on the history
            message = message[message.find(":"):]
            relation_tag = await get_response(f"generate keyword for below query:\n{message}\n")
            # relation_tag = await asyncio.get_event_loop().run_in_executor(None, llm.invoke, )
            agent_logger.debug(f"Message to query: {message}")
            agent_logger.debug(f"Relation tag: {relation_tag}")
            body = {
                # "collection_name": "OpenWebUI_HTML",
                # "collection_name": "BTL",
                "collection_name": "WebUI_Markdown",
                "query": relation_tag,
                "n_result": 5
            }
            async with session.post("/query_collection", json=body) as responses:
                responses = await responses.json()
                responses = responses.get("result", [])
                # agent_logger.debug(f"After calling retrieval tool: {responses}")
                agent_logger.debug(f"After calling retrieval tool:\n{''.join([r.get('document', '') for r in responses])}")
                context = []
                for response in responses:
                    context.append(response.get("document", ""))
                return {
                    "context": context
                }
    except Exception as e:
        agent_logger.debug(f"Error querying RAG: {e}")
        raise e

async def _summary_rag(state: AgentState):
    agent_logger.info("Node: summary_context")
    try:
        agent_logger.info(f"summary retrieval information...")
        prompt = """you are an context summarizer in a agent flow. Your job is summary the context queried from database.
        Your summary should be actionable, have strong relation to user query.
        Your process should be:
        - reading this:
        <user_last_query>\n{}\n</user_last_query>
        <retrieval_context>\n{}\n</retrieval_context>
        
        - looking for relavent information the context above
        - Include all the information to the answer with format below as your final answer:
        
        <summary>
            <context>
                [summary of the context]
            </context>

            <code>
                [all code part]
                [all command instruction]
                (You must not give any extra information other than what provided in the context above.)
            </code>

            <config>
                [all config for application]
                (You must not give any extra information other than what provided in the context above.)
            </config>

            <relevant_rate>
                [explain why this context is relevant (or not relavent) to user query]
            </relevant_rate>
        </summary>

        Provide your response using the following header structure exactly as shown, including all sections (<summary>, <context>, <code>, <config>, <relevant_rate>, and closing for each section).
        Remember to add </summary> as ending for your response.
        If a context is not relevant or does not have enough action, skip that context by return <summary></summary>
        If a section does not apply or lacks content, include it with a brief note explaining why it is empty or not applicable."""
        
        message = state["chat_history"][-1]
        agent_logger.debug(f"chat message: {message}")
        agent_logger.debug(f"number of context: {len(state['context'])}")
        contextes = []
        # for context in state["context"]:
        #     response = await asyncio.get_event_loop().run_in_executor(None, llm.invoke, prompt.format(message, context))
        #     agent_logger.debug(f"summary context:\n{extract_context_summary_response(response)}")
        #     contextes.append(extract_context_summary_response(response))
        # return {
        #     "context": contextes
        # }
    except Exception as e:
        agent_logger.debug(f"Error summary context: {e}")
        raise e
    
def _should_retrieval(state: AgentState) -> bool:
    try:
        agent_logger.info(f"Conditional Edege: Should_Retrieval")
        if state["task"] != "chat":
            agent_logger.debug("No need to query rag")
            return False
        message = state["chat_history"][-1]
        message = message[message.find(":"):]
        agent_logger.debug(f"Message recieved: {message}")
        # Keyword Detection
        potential_queries = ["search", "openwebui", "webui", "btl"]
        for potential in potential_queries:
            if potential in message.lower():
                agent_logger.debug("Familiar keywork detected, query rag")
                return True
        agent_logger.debug("No familiar keywork detected, do not query rag")
        return False
    except Exception as e:
        raise e

async def _decide(state: AgentState):
    agent_logger.debug("Node: making_decision")
    prompt = f"""You are a decision-making agent in an agent flow. Your task is to plan a list of actions based on the provided context and chat history, which can be used to perform tool calls.

    <given_context>
    {''.join(state['context'])}
    </given_context>

    <chat_history>
    {''.join(state['chat_history'])}
    </chat_history>

    To succeed in this task, follow these steps:
    1. Review the <given_context> to understand the available tools, resources, and constraints.
    2. Analyze the <chat_history> to identify the user’s intent and any relevant previous interactions.
    3. Determine the sequence of actions needed to address the user’s query or achieve the goal.
    4. For each action:
    - Specify the action clearly and concisely.
    - Provide the exact code required to execute the action.
    - Explain the purpose of the code and how it contributes to the overall plan.
    5. Ensure all actions and code are derived strictly from the information provided in <given_context>.

    Your response must follow this exact format:
    <step_i>
        <action>
            Description of the action to be performed.
        </action>
        <code>
            Code to execute the action.
        </code>
        <additional_information>
            Explanation of the code and its role in the action plan.
        </additional_information>
    </step_i>

    Include only actions and code that are supported by the <given_context>. Ensure each step is clear, actionable, and relevant to the tool call process.
    Include only actions and code that are explicitly supported by the <given_context>. Do not hallucinate or infer information not present in the context.
    Your answer:
    """

    # answer = await asyncio.get_event_loop().run_in_executor(None, llm.invoke, prompt) + "\n"
    answer = await get_response(prompt) + "\n"
    agent_logger.debug(f"list of actions:\n{answer}")

    return {
        "thinking": [answer]
    }

async def _call_tools(state: AgentState):
    agent_logger.debug("Node: calling_tools")
    prompt = f"""You are an elite configuration testing agent with precise tool-calling capabilities. Your mission is to execute ONLY the actions explicitly defined in the provided thinking session - no more, no less. This prevents hallucination and ensures reliable, predictable behavior.

    CRITICAL OPERATIONAL CONTEXT:
    The target project/repository is pre-installed at /home/ubuntu/{state['repo_name']} or /home/ubuntu/openwebui. Your role is strictly limited to:
    - In the few first attempts, you must avoid starting or running any script, docker or code like docker  or any .sh script.
    - Configure existing installations (modify configs, environment variables)
    - The dependencies were pre installed, avoid installing stuff because you are wasting the virtual machine resources.
    - Test configurations by running existing projects  
    - Use pre-installed services and tools
    - NEVER install, clone, download, or build anything new
    - NEVER make assumptions beyond the thinking session
    - NEVER add actions not explicitly mentioned in thinking session
    - NEVER repeat the same failed approach more than 2 times
    - You are required to make every command specific and executable - you are actually configuring the environment, not providing instructions. For example, do not call '/path/to/project/directory', rather a specific path: '/home/ubuntu/openwebui'
    - If a command fails, analyze the error and try a different approach from the thinking session
    - If the tool is shell_command, you will be given your log for this execution attempt in the next turn

    EXECUTION LOG FORMAT IF THE TOOL CALLED IS SHELL_COMMAND:
    The logs follow this structured format - analyze them carefully:
    [TIMESTAMP] Starting command: <command>
    [TIMESTAMP] Process ID: <uuid>
    ================================================================================
    [TIMESTAMP] <command_output_or_error_message>
    ================================================================================
    [TIMESTAMP] Command finished
    [TIMESTAMP] Status: <failed|completed>
    [TIMESTAMP] Exit code: <number>
    [TIMESTAMP] Log writer stopping

    Key indicators to watch for:
    - Exit code 127: Command not found (missing binary/tool)
    - Exit code 1: General execution error
    - Exit code 125: Wrong command calling, please read the log
    - Exit code 0: Success
    - Status "failed": Command execution failed
    - Status "completed": Command executed successfully
    - if the command is still running, it may need to be monitored further, and it won't have this section:

    ================================================================================
    [TIMESTAMP] Command finished
    [TIMESTAMP] Status: <failed|completed>
    [TIMESTAMP] Exit code: <number>
    [TIMESTAMP] Log writer stopping


    CURRENT STATE ANALYSIS:
    ==================
    THIS IS YOUR ATTEMPT SO FAR: {state['attempt']}
    EXECUTION HISTORY & LESSONS LEARNED:
    {state.get("logs", "No previous execution logs available")}
    ==================

    STRATEGIC EXECUTION PHASES:
    Phase 1 (Intelligence Gathering - First 1-2 attempts):
    - Map project structure with list_directory and search_files
    - Identify configuration files, environment files, and entry points  
    - Understand current system state before making changes
    - Avoid starting or running any script, docker or code like docker compose up -d, docker run or any sh script.

    Phase 2 (Precise Configuration - Based on thinking session):
    - Modify only specified configuration files
    - Apply exact parameter changes from thinking session
    - Test incrementally with validation at each step

    Phase 3 (Validation & Monitoring):
    - Start services using async_execution=true for long-running processes
    - Monitor logs and process status
    - Verify configuration changes produce expected behavior

    <tool_info>
        <tool_name>shell_command</tool_name>
        <description>Executes a shell command in the terminal. Use for running existing projects, setting environment variables, executing pre-installed scripts, running docker-compose on existing projects, starting services, running tests, etc.</description>
        <arguments>
            <command>The shell command to execute.</command>
            <async_execution>Boolean, whether to run the command asynchronously. Only run asynchronously if the command is hosting or serving something (e.g., starting a web server, docker-compose up).</async_execution>
        </arguments>

        <tool_name>read_file</tool_name>
        <description>Reads content from a file with various options (full, head, tail). Use to examine existing configuration files, scripts, documentation.</description>
        <arguments>
            <file_path>Path to the file to read.</file_path>
            <encoding>File encoding (default: utf-8).</encoding>
            <lines>Number of lines to read from start (optional).</lines>
            <tail>Number of lines to read from end (optional).</tail>
        </arguments>

        <tool_name>write_file</tool_name>
        <description>Writes content to a file. Use to modify existing configuration files, create new config files, update environment files, etc.</description>
        <arguments>
            <file_path>Path to the file to write.</file_path>
            <content>Content to write to the file.</content>
            <encoding>File encoding (default: utf-8).</encoding>
            <append>Append to file instead of overwriting (default: false).</append>
            <create_dirs>Create parent directories if they don't exist (default: true).</create_dirs>
        </arguments>

        <tool_name>delete_file</tool_name>
        <description>Deletes a file or directory. Use to clean up temporary files, remove old configurations, etc.</description>
        <arguments>
            <file_path>Path to the file or directory to delete.</file_path>
            <recursive>Delete directories recursively (default: false).</recursive>
        </arguments>

        <tool_name>list_directory</tool_name>
        <description>Lists contents of a directory. IMPORTANT: Use this first to explore the project structure and understand what's already installed.</description>
        <arguments>
            <directory_path>Path to the directory to list.</directory_path>
            <recursive>List files recursively (default: false).</recursive>
            <show_hidden>Show hidden files and directories (default: false).</show_hidden>
            <details>Show detailed file information (default: false).</details>
        </arguments>

        <tool_name>search_files</tool_name>
        <description>Searches for files by pattern and optionally by content. Use to locate configuration files, find specific settings, discover project structure.</description>
        <arguments>
            <directory_path>Directory to search in.</directory_path>
            <pattern>Search pattern (glob style, e.g., '*.py', '*.yml', '*.json', 'docker-compose*', '.env*').</pattern>
            <recursive>Search recursively in subdirectories (default: true).</recursive>
            <content_search>Search for text content within files (optional).</content_search>
        </arguments>

        <tool_name>create_directory</tool_name>
        <description>Creates a new directory. Use for creating log directories, temporary folders, etc.</description>
        <arguments>
            <directory_path>Path to the directory to create.</directory_path>
            <parents>Create parent directories if they don't exist (default: true).</parents>
        </arguments>

        <tool_name>list_processes</tool_name>
        <description>Lists all tracked processes. Use to monitor running services and tests.</description>
        <arguments>
            <process_id>Specific process ID to query (optional).</process_id>
            <status_filter>Filter by status: running, completed, failed, killed (optional).</status_filter>
        </arguments>



        <tool_name>kill_process</tool_name>
        <description>Kills a specific tracked process. Use to stop running services during testing.</description>
        <arguments>
            <process_id>Process ID to terminate.</process_id>
        </arguments>
    </tool_info>

    <thinking_session>
    {''.join(state['thinking'])}
    </thinking_session>

    EXECUTION GUIDELINES:
    1. **Project Exploration First**: Always start by exploring the existing project structure using `list_directory` and `search_files` to understand what's already available.

    2. **Configuration Testing Workflow**:
    - Read existing configuration files to understand current settings
    - Modify configurations as specified in the thinking session
    - Test the changes by running the existing project (not installing new components)
    - Monitor processes and logs to verify configuration changes work

    3. **Tool Selection Rules**:
    - `shell_command`: For running existing scripts, starting services, setting environment variables, executing tests, running docker-compose on existing projects
    - `read_file`/`write_file`: For examining and modifying configuration files, environment files, scripts
    - `list_directory`/`search_files`: For exploring project structure and locating files
    - Process tools: For monitoring and managing running services during testing

    4. **Async Execution**: Set `async_execution=true` ONLY for long-running services like web servers, databases, or `docker-compose up` commands that need to run in the background.

    5. **Validation Requirements**:
    - Every tool call must correspond directly to an action in the `<thinking_session>`
    - Use exact file paths, commands, and parameters from the thinking session
    - Do not add installation, download, or clone operations not explicitly mentioned
    - Focus on configuration testing of existing installations

    Your response must follow this exact format:
    <tool_calls>
        <id>
            Tool call number (increment for multiple calls, starting from 1, this must be 1).
        </id>
        <tool_name>
            Name of the tool to call (refer to `<tool_info>`).
        </tool_name>
        <arguments>
            Arguments for the tool call (refer to `<tool_info>` for required arguments).
        </arguments>
    </tool_calls>
    <tool_calls>
            <id>
                Tool call number (increment for multiple calls, starting from 1, this must be 2).
            </id>
            <tool_name>
                Name of the tool to call (refer to `<tool_info>`).
            </tool_name>
            <arguments>
                Arguments for the tool call (refer to `<tool_info>` for required arguments).
            </arguments>
    </tool_calls>

    Your answer:"""

    agent_logger.debug(f"prompt for tools callings: {prompt}")
    # response = await asyncio.get_event_loop().run_in_executor(None, llm.invoke, prompt)
    response = await get_response(prompt)
    
    agent_logger.debug(f"tool callings: {response}")
    tools = extract_tool_calls_from_xml(response)
    agent_logger.debug(f"tool formated: {tools}")

    # VM_PORT = await aiohttp.ClientSession(url=f"{MULTIPASS_URL}")
    async with aiohttp.ClientSession(f"{MULTIPASS_URL}") as get_vm:
        res = await get_vm.get(url=f"get_free_assigned_vm/{state['agent_id']}")
        res = await res.json()
        # if no vm is assigned, return'
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
        # async with aiohttp.ClientSession(f"{MULTIPASS_URL}") as session:
        #     start_server = await session.post(url=f"start_mcp_server/{state['agent_id']}/{vm_name}")
        #     if start_server.status != 200:
        #         agent_logger.error(f"Failed to start MCP server: {start_server.status}")
        #         return
        VM_IP = str(res['data'][-1]['info']['info']['info'][f'{vm_name}']['ipv4'][0])
        # print(f"VM IP: {VM_IP}")
        async with aiohttp.ClientSession(f"http://{VM_IP}:8000") as session:
            headers = {
                "Content-Type": "application/json",
                "X-API-Key": "API_KEY_PLACEHOLDER"
            }
            results = []
            file_paths = []

            for tool in tools:
                tool_name = tool.get("tool_name")
                async with session.post(f"/invoke", json={
                    "tool_name": tool_name,
                    "arguments": tool.get("arguments", {})
                }, headers=headers,timeout=aiohttp.ClientTimeout(total=1200)) as response:
                    if response.status == 200:
                        result = await response.json()
                        agent_logger.debug(f"Tool {tool_name} executed successfully: {result}")
                        results.append(result)
                        file_path = result.get("result", {}).get("log_file", "").split("/")[-1]
                        file_paths.append(file_path)
                    else:
                        agent_logger.error(f"Failed to execute tool {tool_name}: {response.status}")
            
            # state["results_tool_calls"] = results

            return {
                "results_tool_calls": results,
                "log_file_paths": file_paths,
                "vm_name": vm_name,
                "attempt": state['attempt'] + 1,  # Increment attempt number for next round
            }
                    

async def _check_logs(state: AgentState):
    agent_logger.debug("Node: check_logs")
    agent_logger.debug(f"thinking: {''.join(state['thinking'])}")
    results = state["results_tool_calls"]
    # results = state.get("results_tool_calls", [])
    agent_logger.debug(f"results: {results}")
    log_content = []
    none_shell_content = []
    for result in results:
        if result.get("tool_name", {}) not in ['shell_command']:
            none_shell_content += [result]
    log_content += none_shell_content
    try:
        async with aiohttp.ClientSession(f"{MULTIPASS_URL}") as session:
            # Transfer logs from VM to host via API
            async with session.get(f"/pull_logs/{state['agent_id']}/{state['vm_name']}") as pull_response:
                if pull_response.status != 200:
                    print(f"Failed to pull logs for VM {state['agent_id']}: {await pull_response.text()}")
                agent_logger.debug(f"Logs pulled for agent {state['agent_id']} successfully.")
                # Scan the transferred log directory
                log_dir = os.path.join(LOG_DIR,state['agent_id'], state['vm_name'])
                agent_logger.debug(f"Checking logs in directory: {log_dir}")
                
                if os.path.exists(log_dir):
                    for root, dirs, filenames in os.walk(log_dir):
                        agent_logger.debug(f"Found log files in directory: {root}")
                        for filename in filenames:
                            if filename.endswith('.log'):
                                if filename in state.get("log_file_paths", set()):
                                    file_path = os.path.join(root, filename)
                                    stat_info = os.stat(file_path)
                                    
                                    # Create relative path for virtual_path
                                    relative_path = os.path.relpath(file_path, log_dir)
                                    virtual_path = os.path.join(LOG_DIR, state['agent_id'], state['vm_name'], relative_path)
                                    if not os.path.exists(virtual_path):
                                        agent_logger.warning(f"Log file {virtual_path} does not exist.")
                                        continue
                                    with open(virtual_path, 'r') as file:
                                        logs = file.readlines()
                                        agent_logger.debug(f"Logs from {virtual_path}: {logs}")
                                        log_content.extend(logs)
                else:
                    agent_logger.debug(f"No logs found in directory: {log_dir}")
    except Exception as e:
        agent_logger.debug(f"Error checking logs: {e}")
    # for result in results:
    #     file_path = result.get("result", {}).get("log_file", "").split("/")[-1]
    #     if not file_path:
    #         agent_logger.warning("No log file found in the result.")
    #         continue
    #     agent_logger.debug(f"Checking log file: {file_path}")
    #     file_path = os.path.join(LOG_DIR, state['agent_id'], state['vm_name'], file_path)


    if log_content:
        agent_logger.info(f"Collected logs from all files: {log_content}")
    else:
        agent_logger.info("No logs collected.")

    return {"logs": state["logs"] + log_content}


async def _evaluate_logs(state: AgentState) -> bool:
    """Evaluate action executed"""
    agent_logger.info("Conditional Edge: evaluate logs")
    agent_logger.debug(f"thinking:\n{state['thinking']}")
    logs = state["logs"]
    # logs = "\n".join(logs)
    agent_logger.debug(f"logs: {logs}")
    prompt = f"""You are a log evaluator agent. Your task is to analyze the provided logs and determine if the actions executed were successful or not and then decide whether to continue or repeat the tool calls based on the logs.

    LOG FORMAT TEMPLATE FOR shell_command  TOOL:
    The logs follow this structured format - analyze them carefully:

    [TIMESTAMP] Starting command: <command>
    [TIMESTAMP] Process ID: <uuid>
    ================================================================================
    [TIMESTAMP] <command_output_or_error_message>
    ================================================================================
    [TIMESTAMP] Command finished
    [TIMESTAMP] Status: <failed|completed|running>
    [TIMESTAMP] Exit code: <number>
    [TIMESTAMP] Log writer stopping

    
    When a file operation tool returns a JSON response, provide a clear summary of the operation results based on the JSON structure:

    FOR read_file JSON RESPONSE:
    The JSON contains: file_path (the file that was read), content (the actual file content), encoding (character encoding used), file_info (metadata like size/modification date), and lines_read (number of lines in the content). Summarize the successful read operation and show a brief content preview.

    FOR write_file JSON RESPONSE:
    The JSON contains: file_path (the file that was written to), bytes_written (amount of data written), mode (whether file was "overwritten" or "appended"), and file_info (updated file metadata). Confirm the write operation success and data amount.

    FOR delete_file JSON RESPONSE:
    The JSON contains: message (confirmation of deletion with file path and type). For directories, it indicates if deletion was recursive. Confirm what was deleted and how.

    FOR list_directory JSON RESPONSE:
    The JSON contains: directory (path that was listed), files (array of file/directory names or detailed info), total_count (number of items found), recursive (whether subdirectories were included), show_hidden (whether hidden files were included), and details (whether full file info was provided). Summarize the directory contents found.

    FOR search_files JSON RESPONSE:
    The JSON contains: directory (search location), pattern (search pattern used), content_search (text searched within files), recursive (whether subdirectories were searched), results (array of matching files with paths and optional content matches), and total_matches (number of files found). Summarize search results and matches.

    FOR create_directory JSON RESPONSE:
    The JSON contains: directory_path (the created directory), created (confirmation boolean), parents_created (whether parent directories were made), and directory_info (metadata of new directory). Confirm directory creation.

    FOR ERROR RESPONSES:
    All tools may return JSON with an "error" field containing the error message. Display the error clearly and suggest potential solutions.

    <logs>
    {logs}
    </logs>

    Your answer must be exactly one of these three words (no quotes, no extra text):
    - continue: if errors occurred and need to retry/fix, or next steps should be executed
    - wait: if async processes are running and need time to complete before checking again  
    - complete: if all actions were successful and configuration testing is done

    Answer:
    """
    
    # response = await asyncio.get_event_loop().run_in_executor(None, llm.invoke, prompt)
    response = await get_response(prompt)
    result = str(response).strip().lower().replace("'", "").replace('"', "")
    agent_logger.debug(f"Evaluation response: '{result}'")
    
    # Ensure we return exactly one of the expected values
    if result in ["continue", "wait", "complete"]:
        return result
    else:
        agent_logger.warning(f"Unexpected evaluation result: {result}, defaulting to 'continue'")
        return "continue"

async def _generate_answer(state: AgentState):
    agent_logger.debug("Node: generate_answer")
    try:
        if not state.get("context"):
            state["context"] = []
        prompt = f"""You are a helpful assistant tasked with responding to the user’s last query based solely on the provided thinking session and chat history. The thinking session contains the plan agent’s output, tool call response, and check log agent, while the chat history provides prior user interactions. Do not generate any information or actions beyond what is explicitly provided in the thinking session and chat history to avoid hallucination. If the plan agent omits certain information (e.g., chat history references) in the thinking session, rely only on the explicitly provided data.

        <thinking_session>
        {''.join(state['thinking'])}
        </thinking_session>

        <chat_history>
        {''.join(state['chat_history'])}
        </chat_history>

        To provide an accurate and relevant response, follow these steps:
        1. Identify the user’s last query within the <thinking_session> (e.g., in the additional information or metadata) or, if not present, from the <chat_history>.
        2. Analyze the plan agent’s output, tool call response, and check log agent in the <thinking_session> to determine the primary information available to answer the query.
        3. If the <thinking_session> includes additional information (e.g., metadata or logs), evaluate its relevance to the user’s last query and incorporate it only if applicable.
        4. If the user’s last query explicitly requests relating to previous interactions, use the <chat_history> to inform the response, but only if relevant information is present.
        5. Validate that the response is directly supported by the information in the <thinking_session> and, if applicable, the <chat_history>.
        6. If the query requests specific information not present in either the <thinking_session> or <chat_history>, respond with "I don't know."
        7. Ensure the response is concise, directly addresses the user’s last query, and avoids extraneous details.

        Your response must follow this exact format:
        <answer>
            Response to the user’s last query.
        </answer>

        Provide only the response to the user’s last query, using information explicitly stated in the <thinking_session> and, if relevant, the <chat_history>. If the plan agent omits chat history or other information, do not infer or assume it. If the <thinking_session> and <chat_history> are empty or insufficient to answer the query, respond with "I don't know."

        Your answer:
        """

        # resonse = await asyncio.get_event_loop().run_in_executor(
        #                 None, llm.invoke, prompt
        #             )
        response = await get_response(prompt)
        
        # async with aiohttp.ClientSession(f"{MULTIPASS_URL}") as session:
        #     async with session.get(f"/release_vm/{state['agent_id']}/{state['vm_name']}") as release_res:
        #         agent_logger.debug(f"VM {state['vm_name']} released for agent {state['agent_id']}: {await release_res.text()}")
                

        return {
            "response": f"{response}"
        }
    except Exception as e:
        raise e

# add node
agent.add_node("init_state", _init_state)
agent.add_node("query_Rag", _query_rag)
agent.add_node("summary_context", _summary_rag)
agent.add_node("making_decision", _decide)
agent.add_node("calling_tools", _call_tools)
agent.add_node("check_logs", _check_logs)
agent.add_node("generate_answer", _generate_answer)

# add edge
agent.add_conditional_edges(
    "init_state",
    _should_retrieval,
    {
        True: "query_Rag",
        False: "generate_answer"
    }
)
agent.add_edge("query_Rag", "summary_context")
agent.add_edge("summary_context", "making_decision")
agent.add_edge("making_decision", "calling_tools")

agent.add_edge("calling_tools", "check_logs")
agent.add_conditional_edges(
    "check_logs",
    _evaluate_logs,
    {
        "continue": "calling_tools",    # Keep calling tools (retry/next action)
        "wait": "check_logs",          # Wait and check logs again (async processes running)
        "complete": "generate_answer"   # Done - generate final answer
    }
)

agent.add_edge("generate_answer", END)

agent.set_entry_point("init_state")

agent = agent.compile(checkpointer=None, store=None)

async def run_agent(input_messages: List[Dict[str, Any]]):
    # initial_state = {"messages": input_messages, "task": "chat"}
    input_messages = [f"{m['role']}: {m['content']}" for m in input_messages]
    initial_state = AgentState(
        chat_history=input_messages,
        task="chat"
    )
    agent_logger.debug(f"run agent with state: {initial_state}")
    result = await agent.ainvoke(initial_state)
    return result.get("response", "")

#legacy support
class Agent:
    def __init__(self):
        agent_logger.info("Agent initiated successfully.")
        self.config_agent = agent
        self.coding_agent = None

    async def run_agent(input_messages: List[Dict[str, Any]]):
        # initial_state = {"messages": input_messages, "task": "chat"}
        input_messages = [f"{m['role']}: {m['content']}" for m in input_messages]
        initial_state = AgentState(
            chat_history=input_messages,
            task="chat"
        )
        agent_logger.debug(f"run agent with state: {initial_state}")
        result = await agent.ainvoke(initial_state)
        return result.get("response", "")


#endregion



#region test
if __name__ == "__main__":
    import asyncio
    user_input = [
        # {"role": "user","content": "how to install and run openwebui with docker."},
        # {"role": "user","content": "using the documentation, can you run docker of openwebui in a single line?"},
        {"role": "user","content": "how to disable openai api in webui."},
    ]
    response = asyncio.run(run_agent(user_input))

    print(response)
#endregion
