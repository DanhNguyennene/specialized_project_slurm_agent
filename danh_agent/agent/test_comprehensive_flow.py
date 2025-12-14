"""
Test full flow with various requests
"""
import asyncio
from flow.slurm_structured_agent import SlurmStructuredAgent
from utils.slurm_commands import SlurmCommandBuilder, SlurmCommandSequence

async def test_request(agent, builder, request, num):
    print(f"\n{'='*70}")
    print(f"TEST {num}: {request}")
    print('='*70)
    
    try:
        print("Generating...")
        result = await agent.plan_only(request)
        
        if not result["success"]:
            print(f"❌ Failed: {result.get('error')}")
            return False
        
        sequence = SlurmCommandSequence(**result["sequence"])
        
        print(f"✓ Plan: {sequence.description}")
        print(f"  Commands: {[cmd.command_type for cmd in sequence.commands]}")
        
        validation = builder.validate_sequence(sequence)
        if not validation["valid"]:
            print(f"  ✗ Validation errors: {validation['errors']}")
            return False
        
        output_path = f"/tmp/test_{num}.sh"
        script = builder.compile_to_shell(sequence)
        builder.save_script(sequence, output_path)
        
        print(f"\n{script}")
        print(f"\n✅ Saved: {output_path}")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

async def main():
    print("\n" + "="*70)
    print("COMPREHENSIVE FULL FLOW TESTS")
    print("="*70)
    
    agent = SlurmStructuredAgent(model="qwen2.5:7b", temperature=0.0)
    builder = SlurmCommandBuilder()
    
    tests = [
        "Check job queue",
        "Show cluster information",
        "Submit a training job for 50 epochs on GPU with 8 CPUs and 16GB memory",
        "Check my running jobs",
    ]
    
    results = []
    for i, test in enumerate(tests, 1):
        success = await test_request(agent, builder, test, i)
        results.append(success)
        
        if i < len(tests):
            print("\nWaiting 2 seconds...")
            await asyncio.sleep(2)
    
    print("\n" + "="*70)
    print("RESULTS")
    print("="*70)
    passed = sum(results)
    print(f"✅ Passed: {passed}/{len(tests)}")
    print(f"❌ Failed: {len(tests) - passed}/{len(tests)}")
    
    if passed == len(tests):
        print("\n🎉 ALL TESTS PASSED!")
        print("\nGenerated scripts in /tmp/:")
        for i in range(1, len(tests) + 1):
            print(f"  - test_{i}.sh")

if __name__ == "__main__":
    asyncio.run(main())
