"""
Quick test for enhanced OpenAI client features
"""
import asyncio
from pydantic import BaseModel
from typing import List
from utils.openai_client import OllamaClient


class JobInfo(BaseModel):
    """Structured job information"""
    job_name: str
    num_tasks: int
    time_limit: str
    memory: str


async def test_structured_output():
    """Test structured output with Pydantic"""
    print("\n1. Testing Structured Outputs...")
    client = OllamaClient(model="qwen2.5:7b")
    
    result = await client.chat_structured(
        messages=[
            {"role": "user", "content": "Create a batch job config: name=data_process, 4 tasks, 2 hours, 8GB RAM"}
        ],
        response_format=JobInfo
    )
    
    print(f"✓ Type: {type(result).__name__}")
    print(f"  Job: {result.job_name}")
    print(f"  Tasks: {result.num_tasks}")
    print(f"  Time: {result.time_limit}")
    print(f"  Memory: {result.memory}")


async def test_parallel_tools():
    """Test parallel tool calling"""
    print("\n2. Testing Parallel Tool Calls...")
    client = OllamaClient(model="qwen2.5:7b")
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "check_job",
                "description": "Check job status",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string"}
                    },
                    "required": ["job_id"]
                }
            }
        }
    ]
    
    result = await client.chat_with_tools(
        messages=[
            {"role": "user", "content": "Check status of job 123 and job 456"}
        ],
        tools=tools,
        parallel_tool_calls=True
    )
    
    print(f"✓ Tools called: {len(result['tool_calls'])}")
    for tc in result['tool_calls']:
        print(f"  - {tc['function']['name']}({tc['function']['arguments']})")
    print(f"  Usage: {result['usage']['total_tokens']} tokens")


async def test_streaming():
    """Test streaming"""
    print("\n3. Testing Streaming...")
    client = OllamaClient(model="qwen2.5:7b")
    
    print("  Response: ", end="", flush=True)
    
    chunks = 0
    async for chunk in client.stream_chat(
        messages=[
            {"role": "user", "content": "What is sbatch? Answer in one sentence."}
        ]
    ):
        if chunk["type"] == "content":
            print(chunk["delta"], end="", flush=True)
            chunks += 1
    
    print(f"\n✓ Received {chunks} chunks")


async def test_advanced_params():
    """Test advanced parameters"""
    print("\n4. Testing Advanced Parameters...")
    
    # Test with different temperatures
    client1 = OllamaClient(model="qwen2.5:7b", temperature=0.0, seed=42)
    client2 = OllamaClient(model="qwen2.5:7b", temperature=1.0)
    
    response1 = await client1.simple_chat([
        {"role": "user", "content": "Say hi"}
    ])
    response2 = await client2.simple_chat([
        {"role": "user", "content": "Say hi"}
    ])
    
    print(f"✓ Deterministic (T=0.0): {response1[:50]}")
    print(f"  Creative (T=1.0): {response2[:50]}")


async def test_tool_choice():
    """Test tool_choice parameter"""
    print("\n5. Testing Tool Choice...")
    client = OllamaClient(model="qwen2.5:7b")
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_info",
                "description": "Get information",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    ]
    
    # Test with 'none' - should not call any tool
    result = await client.chat_with_tools(
        messages=[{"role": "user", "content": "Get info"}],
        tools=tools,
        tool_choice="none"
    )
    
    print(f"✓ tool_choice='none': {len(result['tool_calls'])} tools called")
    print(f"  Response: {result['content'][:100]}")
    
    # Test with 'required' - must call at least one tool
    result = await client.chat_with_tools(
        messages=[{"role": "user", "content": "Hello"}],
        tools=tools,
        tool_choice="required"
    )
    
    print(f"✓ tool_choice='required': {len(result['tool_calls'])} tools called")


async def test_usage_tracking():
    """Test token usage tracking"""
    print("\n6. Testing Token Usage Tracking...")
    client = OllamaClient(model="qwen2.5:7b")
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "test",
                "description": "Test function",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    ]
    
    result = await client.chat_with_tools(
        messages=[{"role": "user", "content": "Test"}],
        tools=tools
    )
    
    usage = result['usage']
    print(f"✓ Prompt tokens: {usage['prompt_tokens']}")
    print(f"  Completion tokens: {usage['completion_tokens']}")
    print(f"  Total tokens: {usage['total_tokens']}")


async def main():
    """Run all tests"""
    print("=" * 60)
    print("Enhanced OpenAI Client - Quick Tests")
    print("=" * 60)
    
    tests = [
        test_structured_output,
        test_parallel_tools,
        test_streaming,
        test_advanced_params,
        test_tool_choice,
        test_usage_tracking,
    ]
    
    for test_func in tests:
        try:
            await test_func()
        except Exception as e:
            print(f"\n❌ {test_func.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("Tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
