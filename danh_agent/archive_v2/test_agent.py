"""
Test script for Slurm Agent
"""
import asyncio
from flow.slurm_agent import SlurmAgent


async def test_agent():
    """Test various agent capabilities"""
    
    agent = SlurmAgent()
    
    print("=" * 60)
    print("SLURM AGENT TEST")
    print("=" * 60)
    
    # Test 1: Simple cluster info
    print("\n[Test 1] Checking cluster status...")
    result = await agent.run("Show me the cluster information")
    print(f"Success: {result['success']}")
    print(f"Response: {result['content'][:200]}...")
    print(f"Tools used: {len(result['tool_calls'])}")
    
    # Test 2: Job queue
    print("\n[Test 2] Checking job queue...")
    result = await agent.run("List all jobs in the queue")
    print(f"Success: {result['success']}")
    print(f"Response: {result['content'][:200]}...")
    print(f"Tools used: {len(result['tool_calls'])}")
    
    # Test 3: Conversational
    print("\n[Test 3] Conversational interaction...")
    messages = [
        {"role": "user", "content": "What partitions are available?"}
    ]
    result = await agent.chat(messages)
    print(f"Success: {result['success']}")
    print(f"Response: {result['content'][:200]}...")
    
    # Test 4: Job submission
    print("\n[Test 4] Submitting a test job...")
    result = await agent.run(
        "Submit a test job that runs 'hostname' command with 1 node, "
        "save the script to /tmp/test_job.sh"
    )
    print(f"Success: {result['success']}")
    print(f"Response: {result['content'][:200]}...")
    print(f"Tools used: {len(result['tool_calls'])}")
    
    # Test 5: Simple question (no tools)
    print("\n[Test 5] Simple question...")
    result = await agent.simple_response("What is sbatch used for?")
    print(f"Response: {result[:200]}...")
    
    print("\n" + "=" * 60)
    print("TESTS COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_agent())
