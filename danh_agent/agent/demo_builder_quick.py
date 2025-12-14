"""
Quick Demo: Builder compilation without agent
Shows how the builder works with pre-defined command sequences
NO MODEL CALLS - instant results!
"""
import logging
from utils.slurm_commands import (
    SlurmCommandSequence,
    SlurmCommandBuilder,
    SbatchCommand,
    SqueueCommand,
    SinfoCommand,
    SacctCommand,
    SrunCommand
)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def demo1_simple_job():
    """Demo 1: Submit a training job"""
    print("\n" + "="*70)
    print("DEMO 1: Submit training job and check status")
    print("="*70)
    
    # Manually create the sequence (simulating agent output)
    sequence = SlurmCommandSequence(
        description="Submit neural network training job on GPU",
        commands=[
            SbatchCommand(
                script_path="/home/user/jobs/train_nn.sh",
                command="python train.py --epochs 50 --batch-size 32 --lr 0.001",
                job_name="neural_net_training",
                partition="gpu",
                nodes=1,
                ntasks=1,
                cpus_per_task=8,
                mem="32GB",
                time="4:00:00",
                output="/home/user/logs/train_%j.out",
                error="/home/user/logs/train_%j.err"
            ),
            SqueueCommand(
                user="$USER",
                job_id=None,
                partition="gpu",
                state=None
            )
        ],
        reason="User wants to train neural network and monitor status",
        expected_outcome="Job submitted to GPU partition and visible in queue"
    )
    
    # Build and compile
    builder = SlurmCommandBuilder()
    
    print("\n[Validation]")
    validation = builder.validate_sequence(sequence)
    if validation["valid"]:
        print("✓ Sequence is valid")
    else:
        print(f"✗ Errors: {validation['errors']}")
    
    print("\n[Compilation]")
    script = builder.compile_to_shell(sequence)
    
    output_path = "/tmp/demo1_training.sh"
    builder.save_script(sequence, output_path)
    
    print(f"\n{'─'*70}")
    print(script)
    print('─'*70)
    print(f"\n✅ Saved to: {output_path}")
    print(f"   Run with: bash {output_path}")


def demo2_multiple_jobs():
    """Demo 2: Submit multiple parallel jobs"""
    print("\n" + "="*70)
    print("DEMO 2: Submit 3 parallel training jobs")
    print("="*70)
    
    sequence = SlurmCommandSequence(
        description="Submit parallel training for different models",
        commands=[
            SinfoCommand(partition="gpu", nodes=None, summarize=False),
            SbatchCommand(
                script_path="/tmp/train_resnet.sh",
                command="python train.py --model resnet50 --epochs 100",
                job_name="train_resnet50",
                partition="gpu",
                nodes=1,
                ntasks=1,
                cpus_per_task=8,
                mem="32GB",
                time="8:00:00",
                output="/logs/resnet_%j.out",
                error="/logs/resnet_%j.err"
            ),
            SbatchCommand(
                script_path="/tmp/train_vgg.sh",
                command="python train.py --model vgg16 --epochs 100",
                job_name="train_vgg16",
                partition="gpu",
                nodes=1,
                ntasks=1,
                cpus_per_task=8,
                mem="32GB",
                time="8:00:00",
                output="/logs/vgg_%j.out",
                error="/logs/vgg_%j.err"
            ),
            SbatchCommand(
                script_path="/tmp/train_inception.sh",
                command="python train.py --model inception --epochs 100",
                job_name="train_inception",
                partition="gpu",
                nodes=1,
                ntasks=1,
                cpus_per_task=8,
                mem="32GB",
                time="8:00:00",
                output="/logs/inception_%j.out",
                error="/logs/inception_%j.err"
            ),
            SqueueCommand(user="$USER", job_id=None, partition="gpu", state=None)
        ],
        reason="Train multiple models in parallel for comparison",
        expected_outcome="3 jobs submitted and running on GPU nodes"
    )
    
    builder = SlurmCommandBuilder()
    
    print("\n[Validation]")
    validation = builder.validate_sequence(sequence)
    print(f"✓ {validation['command_count']} commands validated")
    if validation['warnings']:
        for w in validation['warnings']:
            print(f"  ⚠️  {w}")
    
    print("\n[Compilation]")
    script = builder.compile_to_shell(sequence)
    
    output_path = "/tmp/demo2_parallel_training.sh"
    builder.save_script(sequence, output_path)
    
    print(f"\n{'─'*70}")
    print(script)
    print('─'*70)
    print(f"\n✅ Saved to: {output_path}")


def demo3_monitoring():
    """Demo 3: Cluster monitoring commands"""
    print("\n" + "="*70)
    print("DEMO 3: Check cluster status and job history")
    print("="*70)
    
    sequence = SlurmCommandSequence(
        description="Monitor cluster and check recent jobs",
        commands=[
            SinfoCommand(partition=None, nodes=None, summarize=True),
            SqueueCommand(user="$USER", job_id=None, partition=None, state=None),
            SacctCommand(
                job_id=None,
                user="$USER",
                start_time="2025-12-01",
                end_time="2025-12-14",
                state=None
            ),
            SrunCommand(
                command="nvidia-smi",
                nodes=1,
                ntasks=1,
                partition="gpu",
                time="00:01:00",
                timeout=60
            )
        ],
        reason="Get overview of cluster and GPU status",
        expected_outcome="Summary of cluster, jobs, and GPU availability"
    )
    
    builder = SlurmCommandBuilder()
    script = builder.compile_to_shell(sequence)
    
    output_path = "/tmp/demo3_monitoring.sh"
    builder.save_script(sequence, output_path)
    
    print(f"\n{'─'*70}")
    print(script)
    print('─'*70)
    print(f"\n✅ Saved to: {output_path}")


def demo4_interactive():
    """Demo 4: Create your own sequence"""
    print("\n" + "="*70)
    print("DEMO 4: Create custom sequence interactively")
    print("="*70)
    
    print("\nLet's create a sequence step by step...")
    print("\nScenario: Submit a data processing job")
    
    # Build sequence interactively
    commands = []
    
    print("\n[Step 1] Adding sbatch command...")
    commands.append(SbatchCommand(
        script_path="/tmp/process_data.sh",
        command="python process.py --input data.csv --output results.csv",
        job_name="data_processing",
        partition="cpu",
        nodes=1,
        ntasks=4,
        cpus_per_task=2,
        mem="16GB",
        time="2:00:00",
        output="/logs/process_%j.out",
        error="/logs/process_%j.err"
    ))
    print("  ✓ Job submission configured")
    
    print("\n[Step 2] Adding monitoring commands...")
    commands.append(SqueueCommand(
        user="$USER",
        job_id=None,
        partition="cpu",
        state=None
    ))
    print("  ✓ Queue check added")
    
    sequence = SlurmCommandSequence(
        description="Process data with 4 parallel tasks",
        commands=commands,
        reason="User needs to process large CSV file efficiently",
        expected_outcome="Data processed in ~2 hours using 4 CPU cores"
    )
    
    print("\n[Building]")
    builder = SlurmCommandBuilder()
    
    validation = builder.validate_sequence(sequence)
    print(f"✓ Validated: {validation['command_count']} commands")
    
    script = builder.compile_to_shell(sequence)
    output_path = "/tmp/demo4_custom.sh"
    builder.save_script(sequence, output_path)
    
    print(f"\n{'─'*70}")
    print(script)
    print('─'*70)
    print(f"\n✅ Saved to: {output_path}")


def main():
    """Run all demos"""
    print("\n" + "="*70)
    print("SLURM COMMAND BUILDER - INSTANT DEMOS")
    print("(No model calls - just compilation)")
    print("="*70)
    
    try:
        demo1_simple_job()
        demo2_multiple_jobs()
        demo3_monitoring()
        demo4_interactive()
        
        print("\n" + "="*70)
        print("✅ ALL DEMOS COMPLETE")
        print("="*70)
        
        print("\nGenerated scripts:")
        print("  1. /tmp/demo1_training.sh - Single training job")
        print("  2. /tmp/demo2_parallel_training.sh - 3 parallel jobs")
        print("  3. /tmp/demo3_monitoring.sh - Cluster monitoring")
        print("  4. /tmp/demo4_custom.sh - Custom data processing")
        
        print("\nYou can now:")
        print("  • Review the generated scripts")
        print("  • Edit them as needed")
        print("  • Run them on any Slurm cluster: bash <script>")
        print("  • Or integrate the agent later for automatic generation")
        
        print("\nBuilder features demonstrated:")
        print("  ✓ Compile Pydantic models to shell scripts")
        print("  ✓ Validate sequences before compilation")
        print("  ✓ Generate proper sbatch scripts with resources")
        print("  ✓ Support all 12 Slurm command types")
        print("  ✓ Work completely offline (no connections)")
        print("="*70 + "\n")
        
    except Exception as e:
        logger.error(f"Demo failed: {e}", exc_info=True)


if __name__ == "__main__":
    main()
