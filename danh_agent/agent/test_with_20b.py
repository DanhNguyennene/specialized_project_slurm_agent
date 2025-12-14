"""
Test full flow with larger model (gpt-oss:20b)
Should be faster and more capable with structured outputs
"""
import asyncio
from flow.slurm_structured_agent import SlurmStructuredAgent
from utils.slurm_commands import SlurmCommandBuilder, SlurmCommandSequence

async def main():
    print("\n" + "="*70)
    print("FULL FLOW TEST with gpt-oss:20b")
    print("="*70)
    
    # Use 20B model - should be faster and better
    agent = SlurmStructuredAgent(
        model="gpt-oss:20b",
        temperature=0.0
    )
    builder = SlurmCommandBuilder()
    
    test_cases = [
        "Check job queue",
        "Show cluster information", 
        "Submit a GPU training job for 50 epochs with 8 CPUs and 16GB RAM",
    ]
    
    for i, request in enumerate(test_cases, 1):
        print(f"\n{'='*70}")
        print(f"TEST {i}/{len(test_cases)}: {request}")
        print('='*70)
        
        try:
            print("Generating plan...")
            result = await agent.plan_only(request)
            
            if not result["success"]:
                print(f"❌ Failed: {result.get('error')}")
                continue
            
            sequence = SlurmCommandSequence(**result["sequence"])
            
            print(f"\n✅ Generated!")
            print(f"   Description: {sequence.description}")
            print(f"   Commands: {[cmd.command_type for cmd in sequence.commands]}")
            
            # Validate
            validation = builder.validate_sequence(sequence)
            if not validation["valid"]:
                print(f"   ✗ Validation failed: {validation['errors']}")
                continue
            
            print("   ✓ Validation passed")
            
            # Compile
            script = builder.compile_to_shell(sequence)
            output_path = f"/tmp/test_20b_{i}.sh"
            builder.save_script(sequence, output_path)
            
            print(f"\n{'─'*70}")
            print(script)
            print('─'*70)
            print(f"\n✅ Saved: {output_path}")
            
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "="*70)
    print("✅ TESTS COMPLETE with gpt-oss:20b")
    print("="*70)

if __name__ == "__main__":
    print("\n⏱️  Using 20B model - should be faster than 7B for structured outputs")
    asyncio.run(main())
