"""
Simple Multi-Agent Demo

Shows:
1. Chat with user (explain concepts)
2. Generate Slurm commands  
3. Validate and save scripts

Uses qwen3-coder:latest - fast structured outputs!
"""
import asyncio
import sys
sys.path.insert(0, '/mnt/e/workspace/uni/specialized_project/danh_agent/agent')

from flow.multi_agent_system import MultiAgentOrchestrator


async def demo_simple():
    """Simple demo - just ask for a command"""
    print("\n" + "="*70)
    print("DEMO: Submit a GPU training job")
    print("="*70 + "\n")
    
    orchestrator = MultiAgentOrchestrator()
    
    # User request
    request = "I need to submit a PyTorch training job with 4 GPUs"
    
    await orchestrator.run_conversation(request)


async def demo_with_question():
    """Demo with question first, then command"""
    print("\n" + "="*70)
    print("DEMO: Explain then generate")
    print("="*70 + "\n")
    
    orchestrator = MultiAgentOrchestrator()
    
    # First ask a question
    print("\n--- Part 1: Ask about GRES ---")
    messages = []
    messages.append({"role": "user", "content": "What is GRES in Slurm?"})
    print(f"👤 User: What is GRES in Slurm?")
    
    response = await orchestrator.run_turn(orchestrator.chat_agent, messages)
    messages.extend(response.messages)
    
    # Then request commands
    print("\n--- Part 2: Generate command ---")
    messages.append({"role": "user", "content": "Now generate a command to request 2 GPUs"})
    print(f"👤 User: Now generate a command to request 2 GPUs")
    
    response = await orchestrator.run_turn(response.agent, messages)
    
    print("\n" + "="*70)
    print("✅ DEMO COMPLETE")
    print("="*70)


async def demo_knowledge_search():
    """Demo knowledge base search"""
    print("\n" + "="*70)
    print("DEMO: Knowledge base search")
    print("="*70 + "\n")
    
    orchestrator = MultiAgentOrchestrator()
    
    # First, generate some commands to populate knowledge base
    print("📝 Populating knowledge base...")
    await orchestrator.generate_slurm_commands("Check job queue")
    await orchestrator.generate_slurm_commands("Submit GPU job")
    
    print(f"\n📊 Knowledge base now has {len(orchestrator.knowledge_base['slurm_commands'])} entries")
    
    # Now search it
    print("\n🔍 Searching knowledge base for 'gpu'...")
    result = orchestrator.search_knowledge_base("gpu")
    print(f"\nResults:\n{result}")
    
    print("\n" + "="*70)
    print("✅ DEMO COMPLETE")
    print("="*70)


async def main():
    print("\n" + "🌟"*35)
    print("MULTI-AGENT SYSTEM DEMOS")
    print("🌟"*35)
    
    demos = [
        ("Simple command generation", demo_simple),
        ("Knowledge base search", demo_knowledge_search),
    ]
    
    for i, (name, demo_func) in enumerate(demos, 1):
        print(f"\n\n{'#'*70}")
        print(f"DEMO {i}/{len(demos)}: {name}")
        print('#'*70)
        
        try:
            await demo_func()
        except Exception as e:
            print(f"\n❌ Demo failed: {e}")
            import traceback
            traceback.print_exc()
        
        if i < len(demos):
            await asyncio.sleep(1)
    
    print(f"\n\n{'='*70}")
    print("✅ ALL DEMOS COMPLETE")
    print('='*70)


if __name__ == "__main__":
    asyncio.run(main())
