"""
Full flow test with qwen3-coder:latest - should be MUCH faster!
"""
import asyncio
import sys

# Add parent directory to path
sys.path.insert(0, '/mnt/e/workspace/uni/specialized_project/danh_agent/agent')

from flow.slurm_structured_agent import SlurmStructuredAgent
from utils.slurm_commands import SlurmCommandBuilder


async def test_full_flow():
    print("⚡ Using qwen3-coder:latest - should be 10x faster!\n")
    print("="*70)
    print("FULL FLOW TEST: Agent → Builder → Executable Script")
    print("="*70)
    
    # Initialize agent with qwen3-coder
    agent = SlurmStructuredAgent(model="qwen3-coder:latest")
    
    # Test request
    request = "Check the job queue and show cluster information"
    print(f"\n[1] User Request: '{request}'")
    
    # Generate plan
    print(f"\n[2] Agent generating plan...")
    print(f"    (Should take only ~5-10 seconds with qwen3-coder)")
    
    result = await agent.plan_only(request)
    
    # Extract sequence from result
    from utils.slurm_commands import SlurmCommandSequence
    sequence = SlurmCommandSequence(**result["sequence"])
    
    print(f"\n✅ [3] Agent generated plan!")
    print(f"\n    Description: {sequence.description}")
    print(f"    Commands ({len(sequence.commands)}):")
    for i, cmd in enumerate(sequence.commands, 1):
        print(f"      {i}. {cmd.__class__.__name__.replace('Command', '').lower()}")
    
    # Build script
    print(f"\n[4] Building shell script...")
    builder = SlurmCommandBuilder()
    
    # Validate
    validation = builder.validate_sequence(sequence)
    if not validation["valid"]:
        print(f"    ✗ Validation errors:")
        for error in validation["errors"]:
            print(f"      - {error}")
        return
    else:
        print(f"    ✓ Validation passed")
    
    # Compile to shell script
    script_content = builder.compile_to_shell(sequence)
    
    # Save
    script_path = "/tmp/qwen3_coder_test.sh"
    builder.save_script(sequence, script_path)
    
    print(f"\n✅ [5] Script generated!")
    print(f"\n{'-'*70}")
    print(script_content)
    print(f"{'-'*70}")
    
    print(f"\n📁 Saved to: {script_path}")
    print(f"🚀 Run on Slurm: bash {script_path}")
    
    print(f"\n{'='*70}")
    print("✅ FULL FLOW SUCCESSFUL!")
    print("="*70)
    print(f"\nFlow completed:")
    print(f"  1. ✓ User request received")
    print(f"  2. ✓ Agent generated structured plan (FAST with qwen3-coder!)")
    print(f"  3. ✓ Builder validated sequence")
    print(f"  4. ✓ Compiled to executable shell script")
    print(f"  5. ✓ Saved and ready to run on Slurm")
    print(f"\nNo Slurm connection needed - script is portable!")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(test_full_flow())
