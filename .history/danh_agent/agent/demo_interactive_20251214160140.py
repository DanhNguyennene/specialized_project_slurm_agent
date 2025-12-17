"""
Interactive Demo - User Confirmation at Each Step

Run this in a terminal (not a notebook) for interactive prompts!
"""
import asyncio
import sys
sys.path.insert(0, '/mnt/e/workspace/uni/specialized_project/danh_agent/agent')

from flow.react_agent import FullAgenticSystem


async def interactive_demo():
    """Demo with user confirmation at each step"""
    
    print("\n" + "="*60)
    print("🎮 INTERACTIVE AGENTIC DEMO")
    print("="*60)
    print("\nAt each step, you'll be asked to confirm:")
    print("  y = proceed with action")
    print("  n = skip this action")
    print("  q = quit")
    print("="*60 + "\n")
    
    # Create system with interactive=True
    system = FullAgenticSystem(
        model="qwen3-coder:latest",
        interactive=True  # Enable user confirmation!
    )
    
    goal = """Create a GPU training job:
1. Explain what GPUs are needed
2. Generate a job script for 4 GPUs
3. Validate and save"""

    await system.run_react_loop(goal, max_steps=6)


if __name__ == "__main__":
    print("\n⚠️  This demo requires terminal input!")
    print("If running from a script, use: python demo_interactive.py\n")
    
    asyncio.run(interactive_demo())
