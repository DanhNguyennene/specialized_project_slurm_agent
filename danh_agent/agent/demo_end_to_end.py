"""
End-to-End Demo: Agent → Builder → Executable Shell Script
This demonstrates the complete workflow WITHOUT needing Slurm connection
"""
import asyncio
import logging
from flow.slurm_structured_agent import SlurmStructuredAgent
from utils.slurm_commands import SlurmCommandBuilder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def demo_workflow():
    """Complete workflow from user request to executable script"""
    
    print("\n" + "="*70)
    print("END-TO-END DEMO: Agent → Builder → Shell Script")
    print("="*70)
    
    # Initialize agent
    agent = SlurmStructuredAgent(
        model="qwen2.5:7b",
        temperature=0.0
    )
    
    # User requests
    test_requests = [
        "Submit a batch job that trains a neural network for 50 epochs on GPU partition with 8 CPUs and 32GB memory",
        "Check all running jobs and cluster GPU availability",
        "Submit 3 parallel training jobs for resnet, vgg, and inception models, then monitor them"
    ]
    
    for i, user_request in enumerate(test_requests, 1):
        print(f"\n{'='*70}")
        print(f"DEMO {i}: {user_request}")
        print('='*70)
        
        try:
            # Step 1: Agent generates command sequence
            print("\n[Step 1] Agent generating command plan...")
            result = await agent.plan_only(user_request)
            
            if not result["success"]:
                print(f"❌ Failed: {result.get('error')}")
                continue
            
            sequence_dict = result["sequence"]
            print(f"✓ Generated: {sequence_dict['description']}")
            print(f"  Commands: {len(sequence_dict['commands'])}")
            for j, cmd in enumerate(sequence_dict['commands'], 1):
                print(f"    {j}. {cmd['command_type']}")
            
            # Step 2: Create sequence object
            from utils.slurm_commands import SlurmCommandSequence
            sequence = SlurmCommandSequence(**sequence_dict)
            
            # Step 3: Validate
            print("\n[Step 2] Validating sequence...")
            builder = SlurmCommandBuilder()
            validation = builder.validate_sequence(sequence)
            
            if not validation["valid"]:
                print(f"❌ Validation failed:")
                for error in validation["errors"]:
                    print(f"  - {error}")
            else:
                print("✓ Validation passed")
            
            if validation["warnings"]:
                print("⚠️  Warnings:")
                for warning in validation["warnings"]:
                    print(f"  - {warning}")
            
            # Step 4: Compile to shell
            print("\n[Step 3] Compiling to shell script...")
            shell_script = builder.compile_to_shell(sequence)
            
            # Step 5: Save to file
            output_path = f"/tmp/slurm_demo_{i}.sh"
            builder.save_script(sequence, output_path)
            
            print(f"✓ Saved to: {output_path}")
            print(f"\n{'─'*70}")
            print("GENERATED SCRIPT:")
            print('─'*70)
            print(shell_script)
            print('─'*70)
            
            print(f"\n✅ Demo {i} complete!")
            print(f"   You can now run: bash {output_path}")
            
        except Exception as e:
            print(f"❌ Error: {e}")
            logger.error(f"Demo {i} failed", exc_info=True)
    
    print("\n" + "="*70)
    print("ALL DEMOS COMPLETE")
    print("="*70)
    print("\nWhat just happened:")
    print("  1. ✓ Agent understood natural language requests")
    print("  2. ✓ Generated structured Slurm command sequences")
    print("  3. ✓ Validated parameters and safety")
    print("  4. ✓ Compiled to executable shell scripts")
    print("  5. ✓ Saved scripts ready to run on any Slurm cluster")
    print("\nNo Slurm connection needed - pure compilation!")
    print("="*70)


async def interactive_mode():
    """Interactive mode for testing"""
    print("\n" + "="*70)
    print("INTERACTIVE MODE")
    print("="*70)
    print("Enter requests (or 'quit' to exit)")
    print("Example: Submit a job to train a model for 100 epochs")
    print("="*70 + "\n")
    
    agent = SlurmStructuredAgent(model="qwen2.5:7b", temperature=0.0)
    builder = SlurmCommandBuilder()
    
    counter = 1
    
    while True:
        try:
            user_input = input(f"\n[{counter}] Your request: ").strip()
            
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break
            
            if not user_input:
                continue
            
            print("\nProcessing...")
            
            # Generate plan
            result = await agent.plan_only(user_input)
            
            if not result["success"]:
                print(f"❌ Error: {result.get('error')}")
                continue
            
            # Parse sequence
            from utils.slurm_commands import SlurmCommandSequence
            sequence = SlurmCommandSequence(**result["sequence"])
            
            # Validate
            validation = builder.validate_sequence(sequence)
            
            print(f"\n✓ Plan: {sequence.description}")
            print(f"  Commands: {len(sequence.commands)}")
            for i, cmd in enumerate(sequence.commands, 1):
                print(f"    {i}. {cmd.command_type}")
            
            if validation["warnings"]:
                print("\n⚠️  Warnings:")
                for w in validation["warnings"]:
                    print(f"    - {w}")
            
            # Ask to compile
            compile = input("\nCompile to shell script? (y/n): ").strip().lower()
            
            if compile == 'y':
                output_path = f"/tmp/slurm_interactive_{counter}.sh"
                builder.save_script(sequence, output_path)
                
                shell_script = builder.compile_to_shell(sequence)
                print(f"\n{'─'*70}")
                print(shell_script)
                print('─'*70)
                print(f"\n✓ Saved to: {output_path}")
                
                counter += 1
            
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"❌ Error: {e}")
            logger.error("Interactive mode error", exc_info=True)


async def main():
    """Main entry point"""
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
        await interactive_mode()
    else:
        await demo_workflow()


if __name__ == "__main__":
    asyncio.run(main())
