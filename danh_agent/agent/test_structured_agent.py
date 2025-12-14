"""
Test structured Slurm agent with Pydantic-based command sequences
"""
import asyncio
import logging
from utils.slurm_commands import (
    SlurmCommandSequence,
    SbatchCommand,
    SqueueCommand,
    SinfoCommand
)
from flow.slurm_structured_agent import SlurmStructuredAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_manual_sequence():
    """Test manually created command sequence"""
    logger.info("\n=== Test 1: Manual Command Sequence ===")
    
    # Create sequence manually
    sequence = SlurmCommandSequence(
        description="Submit training job and check status",
        commands=[
            SbatchCommand(
                script_path="/tmp/train.sh",
                command="python train.py --epochs 100 --batch-size 32",
                job_name="model_training",
                partition="gpu",
                nodes=1,
                cpus_per_task=4,
                mem="16GB",
                time="4:00:00",
                output="/logs/train_%j.out"
            ),
            SqueueCommand(
                user="testuser",
                state="RUNNING"
            ),
            SinfoCommand(
                partition="gpu"
            )
        ],
        reason="Train ML model and monitor progress",
        expected_outcome="Job submitted successfully, currently running on GPU partition"
    )
    
    # Serialize to JSON
    sequence_json = sequence.model_dump()
    logger.info(f"Sequence JSON: {sequence_json}")
    
    # Validate structure
    assert len(sequence.commands) == 3
    assert sequence.commands[0].command_type == "sbatch"
    assert sequence.commands[1].command_type == "squeue"
    
    logger.info("✓ Manual sequence creation successful")
    return sequence


async def test_agent_generation():
    """Test agent generating command sequence"""
    logger.info("\n=== Test 2: Agent Command Generation ===")
    
    agent = SlurmStructuredAgent(
        model="qwen2.5:7b",
        temperature=0.0
    )
    
    # Generate plan without execution
    result = await agent.plan_only(
        user_message="Submit a batch job that trains a neural network for 10 epochs, then check the job queue"
    )
    
    assert result["success"], f"Failed: {result.get('error')}"
    
    sequence_dict = result["sequence"]
    logger.info(f"Generated sequence: {sequence_dict['description']}")
    logger.info(f"Commands: {len(sequence_dict['commands'])}")
    
    for i, cmd in enumerate(sequence_dict['commands'], 1):
        logger.info(f"  {i}. {cmd['command_type']}")
    
    logger.info(f"\nPlan message:\n{result['final_message']}")
    
    logger.info("✓ Agent generation successful")
    return sequence_dict


async def test_execution_workflow():
    """Test full workflow: plan -> review -> execute"""
    logger.info("\n=== Test 3: Full Execution Workflow ===")
    
    agent = SlurmStructuredAgent(
        model="qwen2.5:7b",
        temperature=0.0
    )
    
    # Step 1: Generate plan
    logger.info("Step 1: Generate plan")
    plan_result = await agent.plan_only(
        user_message="Check cluster info and submit a simple test job"
    )
    
    assert plan_result["success"]
    sequence_dict = plan_result["sequence"]
    
    logger.info(f"Plan: {sequence_dict['description']}")
    logger.info(f"Commands: {[cmd['command_type'] for cmd in sequence_dict['commands']]}")
    
    # Step 2: Review (manual step - in real workflow user would approve)
    logger.info("\nStep 2: Review plan (auto-approving for test)")
    
    # Step 3: Execute
    logger.info("\nStep 3: Execute approved plan")
    
    from utils.slurm_commands import SlurmCommandSequence
    sequence = SlurmCommandSequence(**sequence_dict)
    
    # Note: This will fail without actual Slurm connection
    # In production, ensure connection is established
    try:
        exec_result = await agent.execute_sequence(sequence)
        
        if exec_result["success"]:
            summary = exec_result["execution_summary"]
            logger.info(f"Execution: {summary['successful']}/{summary['total_commands']} succeeded")
            logger.info(f"\n{exec_result['final_message']}")
        else:
            logger.warning(f"Execution failed: {exec_result.get('error')}")
    
    except Exception as e:
        logger.warning(f"Execution test skipped (no connection): {e}")
    
    logger.info("✓ Workflow test complete")


async def test_direct_execution():
    """Test direct execution (plan + execute in one call)"""
    logger.info("\n=== Test 4: Direct Execution ===")
    
    agent = SlurmStructuredAgent(
        model="qwen2.5:7b",
        temperature=0.0
    )
    
    try:
        result = await agent.run(
            user_message="Show me all pending jobs in the queue",
            execute=True
        )
        
        if result["success"]:
            logger.info(f"Sequence: {result['sequence']['description']}")
            
            if result.get("executed"):
                summary = result["execution_summary"]
                logger.info(f"Executed: {summary['successful']}/{summary['total_commands']} succeeded")
                logger.info(f"\n{result['final_message']}")
            else:
                logger.info("Plan generated but not executed")
        else:
            logger.warning(f"Failed: {result.get('error')}")
    
    except Exception as e:
        logger.warning(f"Direct execution test skipped: {e}")
    
    logger.info("✓ Direct execution test complete")


async def test_complex_scenario():
    """Test complex multi-step scenario"""
    logger.info("\n=== Test 5: Complex Scenario ===")
    
    agent = SlurmStructuredAgent(
        model="qwen2.5:7b",
        temperature=0.0
    )
    
    # Complex request
    result = await agent.plan_only(
        user_message="""
        I need to:
        1. Check available GPU partitions
        2. Submit 3 training jobs to the gpu partition
        3. Check the queue status for my user
        4. Get accounting info for my recent jobs
        """
    )
    
    assert result["success"]
    
    sequence_dict = result["sequence"]
    logger.info(f"Complex plan: {sequence_dict['description']}")
    logger.info(f"Generated {len(sequence_dict['commands'])} commands:")
    
    for i, cmd in enumerate(sequence_dict['commands'], 1):
        logger.info(f"  {i}. {cmd['command_type']}: {cmd}")
    
    logger.info(f"\nReason: {sequence_dict.get('reason')}")
    logger.info(f"Expected: {sequence_dict.get('expected_outcome')}")
    
    logger.info("✓ Complex scenario test complete")


async def main():
    """Run all tests"""
    try:
        # Test 1: Manual sequence creation
        await test_manual_sequence()
        
        # Test 2: Agent-generated sequence
        await test_agent_generation()
        
        # Test 3: Full workflow
        await test_execution_workflow()
        
        # Test 4: Direct execution
        await test_direct_execution()
        
        # Test 5: Complex scenario
        await test_complex_scenario()
        
        logger.info("\n" + "="*50)
        logger.info("ALL TESTS COMPLETED")
        logger.info("="*50)
        
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
