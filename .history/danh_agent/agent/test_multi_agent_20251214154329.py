"""
Test Multi-Agent System with Handoffs

This demonstrates:
1. Chat Agent answering Slurm questions
2. Automatic handoff to Slurm Agent for command generation
3. Handoff to Execution Agent for validation
4. Knowledge base learning from interactions
"""
import asyncio
import sys
sys.path.insert(0, '/mnt/e/workspace/uni/specialized_project/danh_agent/agent')

from flow.multi_agent_system import MultiAgentOrchestrator


async def test_conversation(query: str):
    """Test a single conversation flow"""
    orchestrator = MultiAgentOrchestrator()
    await orchestrator.run_conversation(query)


async def main():
    print("\n" + "🌟"*35)
    print("TESTING MULTI-AGENT SYSTEM WITH HANDOFFS")
    print("🌟"*35 + "\n")
    
    # Test cases that should trigger different agent handoffs
    test_cases = [
        # Test 1: Simple question (stays with Chat Agent)
        "What is sbatch?",
        
        # Test 2: Command generation (Chat → Slurm → Execution)
        "I need to submit a training job with 4 GPUs and 64GB RAM",
        
        # Test 3: Complex workflow (multiple handoffs)
        "Check the queue, and if there are any failed jobs, show me their details",
        
        # Test 4: Question then action (Chat explains, then Slurm generates)
        "Explain what gres means, then generate a command to request 2 GPUs",
    ]
    
    for i, query in enumerate(test_cases, 1):
        print(f"\n\n{'='*70}")
        print(f"TEST {i}/{len(test_cases)}")
        print('='*70)
        
        try:
            await test_conversation(query)
        except KeyboardInterrupt:
            print("\n\n⏸️  Test interrupted by user")
            break
        except Exception as e:
            print(f"\n❌ Test failed: {e}")
            import traceback
            traceback.print_exc()
        
        if i < len(test_cases):
            print("\n⏳ Waiting 2 seconds before next test...")
            await asyncio.sleep(2)
    
    print(f"\n\n{'='*70}")
    print("✅ ALL TESTS COMPLETE")
    print('='*70)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
