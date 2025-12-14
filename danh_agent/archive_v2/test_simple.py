"""
Test script for Slurm Agent - Simple mode without MCP server
"""
import asyncio
from flow.slurm_agent import SlurmAgent


async def test_agent_simple():
    """Test agent without connecting to Slurm cluster"""
    
    agent = SlurmAgent(model="qwen2.5:7b")
    
    print("=" * 60)
    print("SLURM AGENT TEST - SIMPLE MODE")
    print("=" * 60)
    
    # Test 1: Simple question (no tools needed)
    print("\n[Test 1] Simple question about Slurm...")
    result = await agent.simple_response("What is sbatch used for in Slurm?")
    print(f"Response: {result[:300]}...")
    
    # Test 2: Ask about squeue
    print("\n[Test 2] Explaining squeue command...")
    result = await agent.simple_response("Explain what the squeue command does")
    print(f"Response: {result[:300]}...")
    
    # Test 3: General Slurm question
    print("\n[Test 3] General Slurm overview...")
    result = await agent.simple_response("What are the main Slurm commands for job management?")
    print(f"Response: {result[:400]}...")
    
    print("\n" + "=" * 60)
    print("TESTS COMPLETE")
    print("Note: Tool execution requires Slurm MCP server running on ENV_IP:ENV_PORT")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_agent_simple())
