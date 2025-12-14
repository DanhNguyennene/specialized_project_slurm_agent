"""
Examples demonstrating all OpenAI API features in the enhanced client
"""
import asyncio
from pydantic import BaseModel
from typing import List
from utils.openai_client import OllamaClient


# Example 1: Structured Outputs with Pydantic
class WeatherInfo(BaseModel):
    location: str
    temperature: float
    condition: str
    humidity: int

async def example_structured_output():
    """Structured output with Pydantic model"""
    print("\n=== Example 1: Structured Outputs ===")
    client = OllamaClient(model="qwen2.5:7b")
    
    result = await client.chat_structured(
        messages=[
            {"role": "user", "content": "What's the weather like in Paris? Give temp in celsius"}
        ],
        response_format=WeatherInfo
    )
    
    print(f"Type: {type(result)}")
    print(f"Location: {result.location}")
    print(f"Temperature: {result.temperature}°C")
    print(f"Condition: {result.condition}")


# Example 2: Parallel Tool Calls
async def example_parallel_tools():
    """Multiple tools called simultaneously"""
    print("\n=== Example 2: Parallel Tool Calls ===")
    client = OllamaClient(model="qwen2.5:7b")
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string"}
                    },
                    "required": ["location"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_time",
                "description": "Get current time for a location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string"}
                    },
                    "required": ["location"]
                }
            }
        }
    ]
    
    result = await client.chat_with_tools(
        messages=[
            {"role": "user", "content": "Get weather and time for Paris and Tokyo"}
        ],
        tools=tools,
        parallel_tool_calls=True
    )
    
    print(f"Tool calls made: {len(result['tool_calls'])}")
    for tc in result['tool_calls']:
        print(f"  - {tc['function']['name']}: {tc['function']['arguments']}")
    print(f"Usage: {result['usage']}")


# Example 3: Streaming with Delta Accumulation
async def example_streaming():
    """Stream response with delta accumulation"""
    print("\n=== Example 3: Streaming ===")
    client = OllamaClient(model="qwen2.5:7b")
    
    print("Streaming response: ", end="", flush=True)
    
    full_content = ""
    async for chunk in client.stream_chat(
        messages=[
            {"role": "user", "content": "Explain what is Slurm in 2 sentences"}
        ]
    ):
        if chunk["type"] == "content":
            print(chunk["delta"], end="", flush=True)
            full_content += chunk["delta"]
        elif chunk["type"] == "done":
            print(f"\n\nFinish reason: {chunk['finish_reason']}")
    
    print(f"Total length: {len(full_content)} chars")


# Example 4: Log Probabilities
async def example_logprobs():
    """Get log probabilities for tokens"""
    print("\n=== Example 4: Log Probabilities ===")
    client = OllamaClient(model="qwen2.5:7b")
    
    result = await client.chat_with_logprobs(
        messages=[
            {"role": "user", "content": "Say 'Hello world'"}
        ],
        top_logprobs=3
    )
    
    print(f"Content: {result['content']}")
    print("\nToken logprobs:")
    for i, token_info in enumerate(result['logprobs']['content'][:5]):
        print(f"  Token {i}: '{token_info['token']}' (logprob: {token_info['logprob']:.4f})")
        if token_info['top_logprobs']:
            print(f"    Alternatives:")
            for alt in token_info['top_logprobs'][:3]:
                print(f"      '{alt['token']}': {alt['logprob']:.4f}")


# Example 5: Force Specific Tool Call
async def example_force_tool():
    """Force model to call a specific function"""
    print("\n=== Example 5: Force Tool Call ===")
    client = OllamaClient(model="qwen2.5:7b")
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "squeue",
                "description": "Check job queue status",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user": {"type": "string", "description": "Username to filter jobs"}
                    },
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "sinfo",
                "description": "View cluster information",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    ]
    
    # Force squeue even if user asks about cluster
    result = await client.force_tool_call(
        messages=[
            {"role": "user", "content": "Show me cluster information"}
        ],
        tools=tools,
        function_name="squeue"
    )
    
    if result:
        print(f"Forced function: {result['function']['name']}")
        print(f"Arguments: {result['function']['arguments']}")


# Example 6: Advanced Parameters
async def example_advanced_params():
    """Use temperature, top_p, frequency_penalty, etc."""
    print("\n=== Example 6: Advanced Parameters ===")
    
    # High temperature for creative response
    client_creative = OllamaClient(
        model="qwen2.5:7b",
        temperature=1.5,
        top_p=0.9,
        frequency_penalty=0.5,
        presence_penalty=0.3
    )
    
    result1 = await client_creative.simple_chat([
        {"role": "user", "content": "Write a creative name for a Slurm job that processes images"}
    ])
    print(f"Creative (temp=1.5): {result1}")
    
    # Low temperature for deterministic response
    client_deterministic = OllamaClient(
        model="qwen2.5:7b",
        temperature=0.0,
        seed=42
    )
    
    result2 = await client_deterministic.simple_chat([
        {"role": "user", "content": "Write a creative name for a Slurm job that processes images"}
    ])
    print(f"Deterministic (temp=0.0, seed=42): {result2}")


# Example 7: Tool Choice Variations
async def example_tool_choice():
    """Different tool_choice modes"""
    print("\n=== Example 7: Tool Choice Variations ===")
    client = OllamaClient(model="qwen2.5:7b")
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "calculate",
                "description": "Perform calculations",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string"}
                    },
                    "required": ["expression"]
                }
            }
        }
    ]
    
    # Auto mode (default)
    print("\n1. tool_choice='auto':")
    result1 = await client.chat_with_tools(
        messages=[{"role": "user", "content": "What is 2+2?"}],
        tools=tools,
        tool_choice="auto"
    )
    print(f"   Tools called: {len(result1['tool_calls'])}")
    
    # Required mode (must call at least one tool)
    print("\n2. tool_choice='required':")
    result2 = await client.chat_with_tools(
        messages=[{"role": "user", "content": "Hello"}],
        tools=tools,
        tool_choice="required"
    )
    print(f"   Tools called: {len(result2['tool_calls'])}")
    
    # None mode (no tools allowed)
    print("\n3. tool_choice='none':")
    result3 = await client.chat_with_tools(
        messages=[{"role": "user", "content": "What is 2+2?"}],
        tools=tools,
        tool_choice="none"
    )
    print(f"   Tools called: {len(result3['tool_calls'])}")
    print(f"   Response: {result3['content']}")


# Example 8: JSON Mode (non-strict)
async def example_json_mode():
    """JSON mode without strict schema"""
    print("\n=== Example 8: JSON Mode ===")
    client = OllamaClient(model="qwen2.5:7b")
    
    response = await client.chat(
        messages=[
            {"role": "user", "content": "List 3 Slurm commands as JSON with name and description"}
        ],
        response_format={"type": "json_object"}
    )
    
    content = response.choices[0].message.content
    print(f"Response (valid JSON):\n{content}")


# Example 9: Multiple Completions (n parameter)
async def example_multiple_completions():
    """Generate multiple completions"""
    print("\n=== Example 9: Multiple Completions ===")
    client = OllamaClient(model="qwen2.5:7b", temperature=0.8)
    
    response = await client.chat(
        messages=[
            {"role": "user", "content": "Suggest a short name for a data processing job (one word)"}
        ],
        n=3
    )
    
    print("Generated options:")
    for i, choice in enumerate(response.choices):
        print(f"  {i+1}. {choice.message.content}")


# Example 10: Streaming Tool Calls
async def example_streaming_tools():
    """Stream tool call arguments as they're generated"""
    print("\n=== Example 10: Streaming Tool Calls ===")
    client = OllamaClient(model="qwen2.5:7b")
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": "Search for information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "category": {"type": "string"}
                    },
                    "required": ["query"]
                }
            }
        }
    ]
    
    print("Streaming tool call arguments:")
    tool_calls = {}
    
    async for chunk in client.stream_chat(
        messages=[
            {"role": "user", "content": "Search for Slurm documentation about job arrays"}
        ],
        tools=tools
    ):
        if chunk["type"] == "tool_call":
            idx = chunk["index"]
            if idx not in tool_calls:
                tool_calls[idx] = {
                    "id": chunk["id"],
                    "name": chunk["function"]["name"] or "",
                    "arguments": ""
                }
            
            if chunk["function"]["name"]:
                tool_calls[idx]["name"] = chunk["function"]["name"]
            if chunk["function"]["arguments"]:
                tool_calls[idx]["arguments"] += chunk["function"]["arguments"]
                print(chunk["function"]["arguments"], end="", flush=True)
        
        elif chunk["type"] == "done":
            print("\n\nFinal tool calls:")
            for idx, tc in tool_calls.items():
                print(f"  {tc['name']}: {tc['arguments']}")


async def main():
    """Run all examples"""
    print("=" * 60)
    print("OpenAI API Features Demo")
    print("=" * 60)
    
    examples = [
        ("Structured Outputs", example_structured_output),
        ("Parallel Tool Calls", example_parallel_tools),
        ("Streaming", example_streaming),
        ("Log Probabilities", example_logprobs),
        ("Force Tool Call", example_force_tool),
        ("Advanced Parameters", example_advanced_params),
        ("Tool Choice", example_tool_choice),
        ("JSON Mode", example_json_mode),
        ("Multiple Completions", example_multiple_completions),
        ("Streaming Tool Calls", example_streaming_tools),
    ]
    
    for name, func in examples:
        try:
            await func()
        except Exception as e:
            print(f"\n❌ {name} failed: {e}")
        
        await asyncio.sleep(0.5)  # Brief pause between examples
    
    print("\n" + "=" * 60)
    print("All examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
