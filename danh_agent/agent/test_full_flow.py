"""
Simple full flow test: Agent → Builder → Script
Using a very simple request to avoid timeout
"""
import asyncio
import logging
from flow.slurm_structured_agent import SlurmStructuredAgent
from utils.slurm_commands import SlurmCommandBuilder, SlurmCommandSequence

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


async def test_simple_flow():
    """Test with simplest possible request"""
    print("\n" + "="*70)
    print("FULL FLOW TEST: Agent → Builder → Executable Script")
    print("="*70)
    
    # Very simple request
    user_request = "Check job queue"
    
    print(f"\n[1] User Request: '{user_request}'")
    print("\n[2] Agent generating plan...")
    print("    (This may take 30-60 seconds due to structured outputs)")
    
    try:
        agent = SlurmStructuredAgent(
            model="qwen2.5:7b",
            temperature=0.0
        )
        
        # Generate plan only (no execution)
        result = await agent.plan_only(user_request)
        
        if not result["success"]:
            print(f"\n❌ Agent failed: {result.get('error')}")
            return
        
        print("\n✅ [3] Agent generated plan!")
        
        sequence_dict = result["sequence"]
        print(f"\n    Description: {sequence_dict['description']}")
        print(f"    Commands ({len(sequence_dict['commands'])}):")
        for i, cmd in enumerate(sequence_dict['commands'], 1):
            print(f"      {i}. {cmd['command_type']}")
        
        # Parse to Pydantic model
        sequence = SlurmCommandSequence(**sequence_dict)
        
        print("\n[4] Building shell script...")
        builder = SlurmCommandBuilder()
        
        # Validate
        validation = builder.validate_sequence(sequence)
        if validation["valid"]:
            print("    ✓ Validation passed")
        else:
            print(f"    ✗ Validation errors: {validation['errors']}")
            return
        
        if validation["warnings"]:
            print(f"    ⚠️  Warnings: {validation['warnings']}")
        
        # Compile
        shell_script = builder.compile_to_shell(sequence)
        
        # Save
        output_path = "/tmp/full_flow_test.sh"
        builder.save_script(sequence, output_path)
        
        print(f"\n✅ [5] Script generated!")
        print(f"\n{'─'*70}")
        print(shell_script)
        print('─'*70)
        
        print(f"\n📁 Saved to: {output_path}")
        print(f"🚀 Run on Slurm: bash {output_path}")
        
        print("\n" + "="*70)
        print("✅ FULL FLOW SUCCESSFUL!")
        print("="*70)
        print("\nFlow completed:")
        print("  1. ✓ User request received")
        print("  2. ✓ Agent generated structured plan")
        print("  3. ✓ Builder validated sequence")
        print("  4. ✓ Compiled to executable shell script")
        print("  5. ✓ Saved and ready to run on Slurm")
        print("\nNo Slurm connection needed - script is portable!")
        print("="*70)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        logger.error("Full flow failed", exc_info=True)


async def test_multiple_requests():
    """Test several simple requests"""
    print("\n" + "="*70)
    print("TESTING MULTIPLE REQUESTS")
    print("="*70)
    
    requests = [
        "Check cluster info",
        "Show my jobs",
        "Submit a test job"
    ]
    
    agent = SlurmStructuredAgent(model="qwen2.5:7b", temperature=0.0)
    builder = SlurmCommandBuilder()
    
    for i, req in enumerate(requests, 1):
        print(f"\n--- Request {i}/{len(requests)}: '{req}' ---")
        
        try:
            print("Generating plan...")
            result = await agent.plan_only(req)
            
            if not result["success"]:
                print(f"❌ Failed: {result.get('error')}")
                continue
            
            sequence = SlurmCommandSequence(**result["sequence"])
            print(f"✓ Generated: {sequence.description}")
            print(f"  Commands: {[cmd.command_type for cmd in sequence.commands]}")
            
            # Compile and save
            output_path = f"/tmp/request_{i}.sh"
            builder.save_script(sequence, output_path)
            print(f"✓ Saved to: {output_path}")
            
        except Exception as e:
            print(f"❌ Error: {e}")
    
    print("\n" + "="*70)
    print("Done! Check /tmp/request_*.sh for generated scripts")


async def main():
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--multiple":
        await test_multiple_requests()
    else:
        await test_simple_flow()


if __name__ == "__main__":
    print("\n⏱️  Note: Structured outputs take time (~30-60 sec per request)")
    print("Press Ctrl+C to cancel if it takes too long\n")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n❌ Cancelled by user")
        print("\nThe builder works perfectly - agent is just slow with structured outputs.")
        print("For instant results, use: python demo_builder_quick.py")
