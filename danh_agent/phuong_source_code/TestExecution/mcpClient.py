import asyncio
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
#from openai import OpenAI
from dotenv import load_dotenv
import json
import re
from langchain_core.messages.base import BaseMessage
import textwrap

# Load environment variables
load_dotenv()

from groq import Groq
import json

# Initialize the Groq client 
client = Groq()

#model = "llama-3.3-70b-versatile"
model = "deepseek-r1-distill-llama-70b"

def LOG(msg: str):
    with open("/home/omni/phuongTran/Test/log/testAgent.1", "a") as file:
        file.write(msg)

class ConnectionManager:
    def __init__(self, sse_server_map):
        self.sse_server_map = sse_server_map
        self.sessions = {}
        self.exit_stack = AsyncExitStack()

    async def initialize(self):
        # Initialize SSE connections
        for server_name, url in self.sse_server_map.items():
            sse_transport = await self.exit_stack.enter_async_context(
                sse_client(url=url)
            )
            read, write = sse_transport
            session = await self.exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()
            self.sessions[server_name] = session
            
    async def list_tools(self):
        tool_map = {}
        consolidated_tools = []
        for server_name, session in self.sessions.items():
            tools = await session.list_tools()
            tool_map.update({tool.name: server_name for tool in tools.tools})
            consolidated_tools.extend(tools.tools)
        return tool_map, consolidated_tools

    async def call_tool(self, tool_name, arguments, tool_map):
        server_name = tool_map.get(tool_name)
        if not server_name:
            print(f"Tool '{tool_name}' not found.")
            return

        session = self.sessions.get(server_name)
        if session:
            result = await session.call_tool(tool_name, arguments=arguments)
            if result.content:
                return result.content[0].text

    async def close(self):
        await self.exit_stack.aclose()


# Chat function to handle interactions and tool calls
async def chat(
    input_messages,
    tool_map,
    tools,
    max_turns=1,
    connection_manager=None,
):
    chat_messages = input_messages[:]
    
    for _ in range(max_turns):
        result = client.chat.completions.create(
            model=model,
            messages=chat_messages,
            tools=tools,
            tool_choice="auto"
        )

        if result.choices[0].finish_reason == "tool_calls":
            chat_messages.append(result.choices[0].message)
            # Loop and call and append to message array
            for tool_call in result.choices[0].message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)

                # Get server name for the tool just for logging
                server_name = tool_map.get(tool_name, "")

                # Log tool call
                log_message = f"**Tool Call**  \n**MCP Server**: `{server_name}`  \n**Tool Name:** `{tool_name}`  \n**Input:**  \n```\n{json.dumps(tool_args, indent=2)}\n```"
                yield BaseMessage(type="assistant", content=log_message)

                # Call the tool and log its observation
                observation = await connection_manager.call_tool(
                    tool_name, tool_args, tool_map
                )
                #observation_mess = {json.dumps(observation, indent=2)}
                observation_mess = observation
                log_message = f"**Tool Observation**  \n**MCP Server**: `{server_name}`  \n**Tool Name:** `{tool_name}`  \n**Output:**  \n```\n{observation_mess}\n```  \n---"
                #print(f"DEBUG\n {json.dumps(observation, indent=2)}")
                #print("DEBUG1\n", observation)
                yield BaseMessage(type="tool", content=log_message)
                
                chat_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(observation),
                    }
                )
        else:
            yield BaseMessage(type="assistant", content=result.choices[0].message.content)

    # Generate a final response if max turns are reached
    #print("✅Before ", chat_messages)
    #result = client.chat.completions.create(
    #    model=model,
    #    messages=chat_messages,
    #)
    #yield {"role": "assistant", "content": result.choices[0].message.content}

def print_pretty_message(msg: str) -> str:
    """
    Prints and returns the message in a centered, decorative format,
    wrapping lines if the message exceeds 80 characters.

    Parameters:
        msg (str): The message to display.

    Returns:
        str: The formatted string with decorative borders.
    """
    width = 80
    border = "*" * width

    # Wrap message to fit within the width minus padding
    wrapped_lines = textwrap.wrap(msg, width=width - 10)
    padded_lines = [line.center(width, "*") for line in wrapped_lines]

    formatted = f"{border}\n" + "\n".join(padded_lines) + f"\n{border}"
    print(formatted)
    return formatted


if __name__ == "__main__":
    sse_server_map = {
        "mcp_test_run": "http://localhost:8001/sse",
    }

    async def main():
        connection_manager = ConnectionManager(sse_server_map)
        await connection_manager.initialize()

        tool_map, tool_objects = await connection_manager.list_tools()

        tools_json = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "strict": True,
                    "parameters": tool.inputSchema,
                },
            }
            for tool in tool_objects
        ]
        #print(tools_json)

        reproduceSuggestion = ""
        with open("/home/omni/phuongTran/Test/log/decisionAgent.1", "r") as f:
            reproduceSuggestion = f.read()
        
        LOG("Recieving from DecisionAgent: " + reproduceSuggestion + "\n\n")

        steps = [step.strip() for step in reproduceSuggestion.split("\n") if step.strip()]
        steps = [re.sub(r"^Step \d+:\s*", "", step) for step in steps]
        #print("Steps: ", steps)
        
        if steps:
            for step in steps:
                #print("++++++++++Executing step: ", step)
                LOG(print_pretty_message("Executing: " + step))
                input_messages = [
                    {
                        "role": "system",
                        "content": "You are a helpful assistant whose ONLY purpose is to use tools to answer user questions.  You MUST use the available tools. Your response MUST have a single tool call.",
                    },
                    {"role": "user", "content": step},
                ]

                async for response in chat(
                    input_messages,
                    tool_map,
                    tools=tools_json,
                    connection_manager=connection_manager,
                ):
                    #print(response)
                    #response.pretty_print()
                    rs = response.pretty_repr()
                    print(rs)
                    LOG(rs)
                #
                #break

        await connection_manager.close()

    asyncio.run(main())