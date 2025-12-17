# python agent_code.py > agent_output.txt 2>&1
import os
from langchain_ollama import OllamaLLM
from langgraph.graph import StateGraph, END, START
import langgraph
import json
import re
import asyncio
from typing import Dict, Any, List, Optional, TypedDict, Annotated,Union
import aiohttp
import logging
from google import genai
from fastmcp.client.client import Client

client = genai.Client(api_key="API_PLACE_HOLDER")

mcp_client = Client("http://10.0.0.4:25000/mcp")

agent_logger_v2 = logging.Logger(name="Agent 009")
agent_logger_v2.setLevel(logging.DEBUG)

# Add a console handler if not already present
if not agent_logger_v2.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    agent_logger_v2.addHandler(console_handler)

__all__ = ["run_agent", "Agent"]

BASE_OLLAMA_URL = "http://localhost:11434"

OLLAMA_MODEL = "gpt-oss:latest"
# using light-weight model before scale up
# OLLAMA_MODEL = "llama3.1:8b-instruct-q8_0"
GEMINI_MODEL = "gemini-2.5-flash"

_rag_server_port = "12000"

CHROMA_HOST = f"http://10.0.0.1:{_rag_server_port}"

ollama_llm = OllamaLLM(
    base_url=BASE_OLLAMA_URL, 
    model=OLLAMA_MODEL,
    # temperature=0.0,
    )

USING_GEMINI=False

async def get_response(prompt: str) -> str:
    if USING_GEMINI:
        response = client.models.generate_content(
            model=GEMINI_MODEL, contents=prompt
        )
        return response.text
    return await asyncio.get_event_loop().run_in_executor(None, ollama_llm.invoke, prompt)

# test ReAct
class AgentState(TypedDict):
    agent_id: str
    chat_history: Annotated[List[str], "The messages in the conversation"]
    conversation: Annotated[List[str], "The messages in the internal interpolation"]
    answer: str
    # conversation: Annotated[str, "The messages in the internal interpolation"]

###
ReAct_prompt_2="""You are a ReAct agent. 
Your reasoning process is structured into nodes: Reason → Action → Observation → (loop or Finish).  

You are provided with tools:
{To Replace Token}

Return only a JSON object, no quotes around the whole object, no explanations

### Node Instructions

1. Reason Node
    - Think step by step about the problem.  
    - Be concise.  
    - Do not provide the answer yet, only internal reasoning.  

2. Action Node  
    - Based on the last Reason, choose exactly one action.

3. Observation Node  
    - Receive the result from the Action.  
    - Summarize it clearly.
"""

class CustomReAct:
    def __init__(self):
        self.llm = get_response # call function to get response
        self.agent = self._create_agent()
        self.mcp = None
        
    def _create_agent(self):
        # design a simple ReActAgent using langgraph stategraph #
        agent = StateGraph(AgentState)

        # add node
        agent.add_node("Init_interpolation", self._init)
        agent.add_node("Get_Context", self._get_context)
        agent.add_node("Reason", self._reason)
        agent.add_node("Action", self._action)
        agent.add_node("Observation", self._observation)
        agent.add_node("Answer", self._answer)

        # add edge
        agent.set_entry_point("Init_interpolation")

        agent.add_edge("Init_interpolation", "Get_Context")
        agent.add_edge("Get_Context", "Reason")
        agent.add_edge("Reason", "Action")
        # agent.add_edge("Action", "Observation")

        agent.add_conditional_edges(
            "Action",
            self._check_action,
            {
                "ReAct": "Observation",
                "Finish": "Answer"
            }
        )
        agent.add_edge("Observation", "Reason")
        agent.add_edge("Answer", END)

        return agent.compile(checkpointer=None, store=None)

    async def _init(self, state: AgentState):
        query = []
        # prepare tool for prompt
        tools = ""
        async with mcp_client as client:
            tools = await client.call_tool(name="get_list_tools", arguments=None)
            tools = "".join([t.text for t in tools.content])
            # tools = await client.get_list_tools()
            # tools = "".join([f"- {t.name}: {t.description}\n" for t in tools])

        query.append(ReAct_prompt_2.replace("{To Replace Token}", tools))
        query.append("User query:\n" + state.get("chat_history", [""])[-1])
                
        return AgentState(
            agent_id=state['agent_id'],
            chat_history = state.get("chat_history", []),
            conversation = query,
        )
    
    async def _search(self, collection: str, query: str):
        try:
            agent_logger_v2.debug(f"collection: {collection}, query: {query}")
            async with aiohttp.ClientSession(CHROMA_HOST) as session:
                agent_logger_v2.debug(f"Successful connect to {CHROMA_HOST}")
                body = {
                    "collection_name": collection,
                    "query": query,
                    "n_result": 1,
                }
                async with session.post("/query_collection", json=body) as responses:
                    if responses.status != 200:
                        responses = await responses.json()
                        return responses['detail']
                    responses = await responses.json()
                    responses = responses.get("result", [])[0]
                    agent_logger_v2.debug(f"After calling retrieval tool: {responses}")
                    response = responses.get("document", "Don't have documents in this collection, make sure the name is right")
                    return response
                    
        except Exception as e:
            agent_logger_v2.debug(f"search function get error: {e}")
            return [e]
        
    async def _get_context(self, state: AgentState):
        agent_logger_v2.debug("Get Collection Node")
        user_input = state["chat_history"][-1]
        # query = await self.llm(f"generate query to search in vector database for this chat (one short sentence): {user_input}\n Reason: Low")
        search_result = await self._search(collection="OpenWebUI_B", query=user_input)
        # Expand to prompt:
        search_result = search_result
        response = json.dumps({ "Observation": {"Context": search_result} }, ensure_ascii=False)

        return {"conversation": state["conversation"] + ["\n" + response + "\n"]}

    async def _reason(self, state: AgentState):
        agent_logger_v2.debug(f"reasoning step: {(len(state['conversation']) + 1) // 3}")
        reason_prompt = "".join(state["conversation"])
        reason_prompt +="""\nYou are at the Reason step of the ReAct loop.  
        Think step by step and explain what you should do next.  
        If you skip or output nothing, the result will be considered invalid.
            
        Output strictly as JSON in this format:  
        { "Reason": "your reasoning here" }"""
        response = ""
        while response == "":
            response = await self.llm(reason_prompt)
        agent_logger_v2.debug(f"Reason: {response}")

        return {"conversation": state["conversation"] + [response + "\n"]}

    async def _action(self, state: AgentState):
        agent_logger_v2.debug(f"action step: {(len(state['conversation']) + 1) // 3}")
        action_prompt = "".join(state["conversation"])
        action_prompt +="""\nYou are at the Action step of the ReAct loop.  
        Think step by step and explain what you should do next.  
        You MUST always output exactly one valid Action in the required format.  
        If you skip or output nothing, the result will be considered invalid.
        Remember cho check for valid JSON format ( equal `{` and `}` ).
        Allowed actions:  
        - {Tool_call: {name: str, arguments: {agr1: value, agr2: value}}} provide and JSON for tool call.
        - {Finish: {summary: str, answer: str}} - when you are confident you can provide the final answer.  
    
        Output strictly as JSON in this format, one JSON at a time:
        { "Action": {"Tool_call": {name: do_a, arguments: {arg1: b, agr2: c}}}" } OR { "Action": {"Finish": {summary: str, answer: str}} }"""
        
        response = ""
        while response == "" or response == "{}":
            response = await self.llm(action_prompt)
        
        agent_logger_v2.debug(f"Action: {response}")

        return {"conversation": state["conversation"] + [response + "\n"]}
    
    async def _observation(self, state: AgentState):
        try:
            agent_logger_v2.debug(f"observation step: {(len(state['conversation']) + 1) // 3}")
            command = state['conversation'][-1]
            command = json.loads(command)
            command = command["Action"]
            command = command['Tool_call']
            name = command.get("name", "Invalid name")
            arguments = command.get("arguments", {})
            observation = [""]
            async with mcp_client as client:
                # agent_logger_v2.debug(f"Tools called: {name}, {arguments}")
                result = await client.call_tool(name=name, arguments=arguments)
                # extract result
                content = result.data
                observation = {"tool result": content}

            agent_logger_v2.debug(f"Observation: {observation}")
        
            # construct response
            response = json.dumps({ "Observation": observation }, ensure_ascii=False)
            return {"conversation": state["conversation"] + [response + "\n"]}
        except Exception as e:
            response = json.dumps({ "Observation": {"error": str(e)} }, ensure_ascii=False)
            return {"conversation": state["conversation"] + [response + "\n"]}


    def _check_action(self, state:AgentState):
        _conversation = state["conversation"]
        if (("Finish".lower() in _conversation[-1].lower()) or 
            (((len(_conversation) + 1) // 3) > 20)):
            return "Finish"
        return "ReAct"
    
    async def _answer(self, state:AgentState):
        answer_prompt = """You are an assistant that converts API execution logs into detailed procedural instructions.
        Given the process of adding a user to a group in OpenWebUI (with actions, endpoints, payloads, and results), generate a step-by-step instruction guide that another developer could follow to reproduce the process manually or programmatically.
        Do not summarize or condense; instead, include:

        The order of steps
        HTTP methods and endpoints
        Headers and payloads used
        Any necessary conditions or checks (e.g., check if the user exists, check if the group exists)
        Expected outputs after each step
        Format the output clearly with numbered steps and sub-steps.

        Output only the detailed instructions based on the following execution log:\n"""

        answer_prompt = answer_prompt.join(state["conversation"][1:])  # skip system prompt
        response = await self.llm(answer_prompt)
        return {
            "answer": response,
        }
        
    async def run_agent(self, input_messages: List[Dict[str, Any]]):
        try:
            this_agent_id = "ReAct 009"
            input_messages = [f"{m['role']}: {m['content']}" for m in input_messages]
            initial_state = AgentState(
                agent_id=this_agent_id,
                chat_history=input_messages
            )

            agent_logger_v2.debug(f"run agent with state: {initial_state}")

            result = await self.agent.ainvoke(initial_state, config={"recursion_limit": 100})

            # agent_logger_v2.debug(f'ReAct trace:\n{"".join(result.get("conversation", [""]))}')

            # reset application config
            async with mcp_client as client:
                await client.call_tool(name="reset_config", arguments=None)

            # return result.get("conversation", [""])[2:-1] + [result.get("answer", "")]
            return [result.get("answer", "")]
        
        except langgraph.errors.GraphRecursionError as recursion_e:
            return {
                "success": False,
                "error": str(recursion_e),
                "messages": ["Maximun recursion loop reached"]
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "messages": []
            }
        
    # async def _get_collection(self):
    #     try:
    #         async with aiohttp.ClientSession(CHROMA_HOST) as session:
    #             agent_logger_v2.debug(f"Successful connect to {CHROMA_HOST}")
    #             async with session.get("/get_list_collection") as responses:
    #                 responses = await responses.json()
    #                 responses = responses.get("set_of_collection", [])
    #                 agent_logger_v2.debug(f"After calling retrieval tool:\n{''.join([r.get('name', '') for r in responses])}")
    #                 collection = []
    #                 for response in responses:
    #                     collection.append(response.get("name", ""))

    #                 return collection
    #     except Exception as e:
    #         agent_logger_v2.debug(f"Get collection function get error: {e}")
    #         raise e
        
















#region test
if __name__ == "__main__":
    import asyncio
    user_input = [
        {"role": "user","content": "Add user loitr to a newgroup in openwebui."},
        # {"role": "user","content": "Add user user123 to a newgroup in openwebui."},
    ]
    
    agent = CustomReAct()
    response = asyncio.run(agent.run_agent(user_input))

    print(response)
#endregion
