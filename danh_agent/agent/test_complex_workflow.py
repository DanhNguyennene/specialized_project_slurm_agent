"""
Test qwen3-coder with complex multi-step Slurm workflows
"""
import asyncio
import sys

sys.path.insert(0, '/mnt/e/workspace/uni/specialized_project/danh_agent/agent')

from flow.slurm_structured_agent import SlurmStructuredAgent
from utils.slurm_commands import SlurmCommandBuilder, SlurmCommandSequence


async def test_complex_workflow(request: str, test_num: int):
    """Test a complex workflow"""
    print(f"\n{'='*70}")
    print(f"TEST {test_num}: {request}")
    print('='*70)
    
    agent = SlurmStructuredAgent(model="qwen3-coder:latest")
    
    print(f"\n⏱️  Generating plan...")
    result = await agent.plan_only(request)
    
    # Extract sequence
    sequence = SlurmCommandSequence(**result["sequence"])
    
    print(f"\n✅ Plan generated!")
    print(f"\n📋 Description: {sequence.description}")
    print(f"\n📝 Commands ({len(sequence.commands)}):")
    for i, cmd in enumerate(sequence.commands, 1):
        cmd_name = cmd.__class__.__name__.replace('Command', '')
        print(f"  {i}. {cmd_name}")
        
        # Show key parameters for each command
        if hasattr(cmd, 'job_script') and cmd.job_script:
            print(f"     └─ Script: {cmd.job_script[:50]}...")
        if hasattr(cmd, 'job_name') and cmd.job_name:
            print(f"     └─ Job: {cmd.job_name}")
        if hasattr(cmd, 'partition') and cmd.partition:
            print(f"     └─ Partition: {cmd.partition}")
        if hasattr(cmd, 'nodes') and cmd.nodes:
            print(f"     └─ Nodes: {cmd.nodes}")
        if hasattr(cmd, 'ntasks') and cmd.ntasks:
            print(f"     └─ Tasks: {cmd.ntasks}")
        if hasattr(cmd, 'gres') and cmd.gres:
            print(f"     └─ GPUs: {cmd.gres}")
        if hasattr(cmd, 'mem') and cmd.mem:
            print(f"     └─ Memory: {cmd.mem}")
        if hasattr(cmd, 'job_id') and cmd.job_id:
            print(f"     └─ Job ID: {cmd.job_id}")
        if hasattr(cmd, 'user') and cmd.user:
            print(f"     └─ User: {cmd.user}")
        if hasattr(cmd, 'format_string') and cmd.format_string:
            print(f"     └─ Format: {cmd.format_string}")
    
    # Build script
    print(f"\n🔨 Building shell script...")
    builder = SlurmCommandBuilder()
    
    validation = builder.validate_sequence(sequence)
    if not validation["valid"]:
        print(f"  ⚠️  Validation warnings:")
        for error in validation["errors"]:
            print(f"    - {error}")
    else:
        print(f"  ✓ Validation passed")
    
    script_content = builder.compile_to_shell(sequence)
    script_path = f"/tmp/complex_test_{test_num}.sh"
    builder.save_script(sequence, script_path)
    
    print(f"\n📄 Generated Script:")
    print(f"{'-'*70}")
    # Show first 20 lines
    lines = script_content.split('\n')
    for line in lines[:20]:
        print(line)
    if len(lines) > 20:
        print(f"... ({len(lines) - 20} more lines)")
    print(f"{'-'*70}")
    
    print(f"\n💾 Saved to: {script_path}")
    print(f"✅ Test {test_num} Complete!\n")


async def main():
    print("\n" + "="*70)
    print("COMPLEX WORKFLOW TESTS with qwen3-coder:latest")
    print("="*70)
    
    # Test cases - from simple to very complex
    test_cases = [
        # 1. Simple monitoring
        "Check the job queue and show cluster node status",
        
        # 2. Job submission with specific resources
        "Submit a PyTorch training job named 'bert-training' that requires 4 GPUs, 64GB RAM, and 16 CPU cores, running for maximum 48 hours on the gpu partition",
        
        # 3. Multi-step workflow: submit + monitor
        "Submit a distributed training job with 2 nodes and 8 GPUs total, then check its status in the queue",
        
        # 4. Job management workflow
        "Show all my running jobs, then check the detailed information for job 12345, and if needed, update its time limit to 72 hours",
        
        # 5. Resource investigation and planning
        "First check which partitions are available and their node status, then show the current job queue, and finally check the accounting information for user 'john' from the last 7 days",
        
        # 6. Complex troubleshooting workflow
        "I need to debug a failed job: check the queue for my jobs, show detailed info about job 67890 including why it failed, check the cluster node status to see if there are resource issues, and finally look at accounting history for that job",
        
        # 7. Batch job management
        "Cancel all my pending jobs in the debug partition, then hold job 11111, release job 22222, and check the priority of all my remaining jobs",
        
        # 8. Comprehensive cluster analysis
        "Give me a complete cluster overview: show all partitions with their resources, list all jobs from all users, check accounting data for the last 24 hours, and show fair share information for all users"
    ]
    
    # Run tests
    for i, request in enumerate(test_cases, 1):
        try:
            await test_complex_workflow(request, i)
        except Exception as e:
            print(f"\n❌ Test {i} failed: {e}")
            import traceback
            traceback.print_exc()
        
        # Small delay between tests
        if i < len(test_cases):
            await asyncio.sleep(1)
    
    print("\n" + "="*70)
    print("✅ ALL COMPLEX TESTS COMPLETE")
    print("="*70)
    print(f"\nTested {len(test_cases)} complex workflows")
    print("All scripts saved to /tmp/complex_test_*.sh")


if __name__ == "__main__":
    asyncio.run(main())
