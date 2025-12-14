"""
Test SlurmCommandBuilder in OFFLINE mode (no Slurm connection needed)
Demonstrates compilation and validation without actual execution
"""
import logging
from utils.slurm_commands import (
    SlurmCommandSequence,
    SlurmCommandBuilder,
    SbatchCommand,
    SqueueCommand,
    ScancelCommand,
    SinfoCommand,
    SacctCommand,
    SrunCommand
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_compile_to_shell():
    """Test compilation of sequence to shell script"""
    logger.info("\n=== Test 1: Compile to Shell Script ===")
    
    # Create sequence
    sequence = SlurmCommandSequence(
        description="Submit training job and monitor",
        commands=[
            SbatchCommand(
                script_path="/tmp/train.sh",
                command="python train.py --epochs 100",
                job_name="ml_training",
                partition="gpu",
                nodes=1,
                ntasks=1,
                cpus_per_task=4,
                mem="16GB",
                time="4:00:00",
                output="/logs/train_%j.out",
                error="/logs/train_%j.err"
            ),
            SqueueCommand(
                user="$USER",
                state=None,
                job_id=None,
                partition=None
            ),
            SinfoCommand(
                partition="gpu",
                nodes=None,
                summarize=False
            )
        ],
        reason="Train model and check cluster status",
        expected_outcome="Job submitted and running on GPU"
    )
    
    # Build without connection
    builder = SlurmCommandBuilder()  # No connection needed!
    
    # Compile to shell
    shell_script = builder.compile_to_shell(sequence)
    
    print("\n" + "="*60)
    print("GENERATED SHELL SCRIPT:")
    print("="*60)
    print(shell_script)
    print("="*60)
    
    logger.info("✓ Shell script compilation successful")
    return shell_script


def test_save_script():
    """Test saving compiled script to file"""
    logger.info("\n=== Test 2: Save Script to File ===")
    
    sequence = SlurmCommandSequence(
        description="Quick cluster check",
        commands=[
            SinfoCommand(partition=None, nodes=None, summarize=True),
            SqueueCommand(user="$USER", job_id=None, partition=None, state=None)
        ]
    )
    
    builder = SlurmCommandBuilder()
    output_path = "/tmp/slurm_test_script.sh"
    
    saved_path = builder.save_script(sequence, output_path)
    
    logger.info(f"✓ Script saved to: {saved_path}")
    
    # Read back and display
    with open(saved_path, 'r') as f:
        content = f.read()
    
    print(f"\nSaved script content:\n{content}")
    
    return saved_path


def test_validation():
    """Test sequence validation"""
    logger.info("\n=== Test 3: Validate Sequences ===")
    
    builder = SlurmCommandBuilder()
    
    # Valid sequence
    valid_seq = SlurmCommandSequence(
        description="Valid job submission",
        commands=[
            SbatchCommand(
                script_path="/tmp/job.sh",
                command="echo 'Hello'",
                job_name="test",
                partition="cpu",
                nodes=1,
                ntasks=1,
                cpus_per_task=1,
                mem="1GB",
                time="00:10:00",
                output=None,
                error=None
            )
        ]
    )
    
    result = builder.validate_sequence(valid_seq)
    logger.info(f"Valid sequence check: {result}")
    assert result["valid"], "Should be valid"
    
    # Invalid sequence - missing required fields
    invalid_seq = SlurmCommandSequence(
        description="Invalid - missing script path",
        commands=[
            SbatchCommand(
                script_path="",  # Empty!
                command="echo test",
                job_name="test",
                partition=None,
                nodes=0,  # Invalid!
                ntasks=1,
                cpus_per_task=1,
                mem=None,
                time="invalid_time",  # Invalid format
                output=None,
                error=None
            )
        ]
    )
    
    result = builder.validate_sequence(invalid_seq)
    logger.info(f"Invalid sequence check: {result}")
    assert not result["valid"], "Should be invalid"
    logger.info(f"Errors found: {result['errors']}")
    logger.info(f"Warnings: {result['warnings']}")
    
    # Dangerous sequence - cancel all user jobs
    dangerous_seq = SlurmCommandSequence(
        description="Cancel all jobs",
        commands=[
            ScancelCommand(
                job_id=None,
                user="$USER",  # Will cancel ALL jobs!
                partition=None,
                state=None
            )
        ]
    )
    
    result = builder.validate_sequence(dangerous_seq)
    logger.info(f"Dangerous sequence check: {result}")
    logger.info(f"Warnings: {result['warnings']}")
    
    logger.info("✓ Validation tests complete")


def test_complex_workflow():
    """Test complex multi-command workflow"""
    logger.info("\n=== Test 4: Complex Workflow ===")
    
    sequence = SlurmCommandSequence(
        description="Full workflow: check cluster, submit jobs, monitor",
        commands=[
            # 1. Check cluster status
            SinfoCommand(partition=None, nodes=None, summarize=True),
            
            # 2. Submit 3 training jobs
            SbatchCommand(
                script_path="/tmp/train1.sh",
                command="python train.py --model=resnet --epochs=50",
                job_name="train_resnet",
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
                script_path="/tmp/train2.sh",
                command="python train.py --model=vgg --epochs=50",
                job_name="train_vgg",
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
                script_path="/tmp/train3.sh",
                command="python train.py --model=inception --epochs=50",
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
            
            # 3. Check queue
            SqueueCommand(user="$USER", job_id=None, partition="gpu", state=None),
            
            # 4. Run quick test
            SrunCommand(
                command="nvidia-smi",
                nodes=1,
                ntasks=1,
                partition="gpu",
                time="00:01:00",
                timeout=60
            ),
            
            # 5. Check accounting
            SacctCommand(
                job_id=None,
                user="$USER",
                start_time="2025-12-01",
                end_time="2025-12-14",
                state=None
            )
        ],
        reason="Submit multiple training jobs and monitor cluster",
        expected_outcome="3 jobs submitted and running, cluster status healthy"
    )
    
    builder = SlurmCommandBuilder()
    
    # Validate
    validation = builder.validate_sequence(sequence)
    logger.info(f"Validation: {validation['command_count']} commands")
    if validation['warnings']:
        logger.warning(f"Warnings: {validation['warnings']}")
    if validation['errors']:
        logger.error(f"Errors: {validation['errors']}")
    
    # Compile
    shell_script = builder.compile_to_shell(sequence)
    
    print("\n" + "="*60)
    print("COMPLEX WORKFLOW SCRIPT:")
    print("="*60)
    print(shell_script)
    print("="*60)
    
    # Save
    output_path = "/tmp/complex_workflow.sh"
    builder.save_script(sequence, output_path)
    
    logger.info(f"✓ Complex workflow compiled and saved to {output_path}")
    logger.info("  You can now run this script on any Slurm cluster!")


def test_all_command_types():
    """Test compilation of all 12 command types"""
    logger.info("\n=== Test 5: All Command Types ===")
    
    from utils.slurm_commands import (
        ScontrolShowCommand, ScontrolUpdateCommand,
        ScontrolHoldCommand, ScontrolReleaseCommand,
        SprioCommand, SshareCommand, EntityType
    )
    
    sequence = SlurmCommandSequence(
        description="Demo all Slurm command types",
        commands=[
            SbatchCommand(
                script_path="/tmp/demo.sh",
                command="echo 'Demo job'",
                job_name="demo",
                partition="cpu",
                nodes=1, ntasks=1, cpus_per_task=1,
                mem="1GB", time="00:05:00",
                output=None, error=None
            ),
            SqueueCommand(user="$USER", job_id=None, partition=None, state=None),
            SinfoCommand(partition=None, nodes=None, summarize=False),
            SacctCommand(job_id=None, user="$USER", start_time=None, end_time=None, state=None),
            ScontrolShowCommand(entity=EntityType.JOB, name="12345"),
            SrunCommand(command="hostname", nodes=1, ntasks=1, partition=None, time=None, timeout=None),
            ScontrolUpdateCommand(entity_type=EntityType.JOB, entity_id="12345", properties={"TimeLimit": "1:00:00"}),
            ScontrolHoldCommand(job_id="12345"),
            ScontrolReleaseCommand(job_id="12345"),
            SprioCommand(job_id=None, user="$USER"),
            SshareCommand(account=None, user="$USER"),
            ScancelCommand(job_id="12345", user=None, partition=None, state=None)
        ]
    )
    
    builder = SlurmCommandBuilder()
    shell_script = builder.compile_to_shell(sequence)
    
    print("\n" + "="*60)
    print("ALL COMMAND TYPES SCRIPT:")
    print("="*60)
    print(shell_script)
    print("="*60)
    
    logger.info("✓ All 12 command types compiled successfully")


def main():
    """Run all builder tests"""
    print("\n" + "="*70)
    print("SLURM COMMAND BUILDER - OFFLINE MODE TESTS")
    print("(No Slurm connection required - just compilation and validation)")
    print("="*70)
    
    try:
        # Test 1: Basic compilation
        test_compile_to_shell()
        
        # Test 2: Save to file
        test_save_script()
        
        # Test 3: Validation
        test_validation()
        
        # Test 4: Complex workflow
        test_complex_workflow()
        
        # Test 5: All command types
        test_all_command_types()
        
        print("\n" + "="*70)
        print("✅ ALL BUILDER TESTS PASSED")
        print("="*70)
        print("\nThe builder can:")
        print("  1. ✓ Compile agent output to shell scripts")
        print("  2. ✓ Validate sequences before execution")
        print("  3. ✓ Save executable scripts to files")
        print("  4. ✓ Work completely OFFLINE (no Slurm needed)")
        print("\nYou can now:")
        print("  - Use the agent to generate command sequences")
        print("  - Compile them to shell scripts")
        print("  - Review/edit the scripts")
        print("  - Run them later when Slurm connection is ready")
        print("="*70)
        
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)


if __name__ == "__main__":
    main()
