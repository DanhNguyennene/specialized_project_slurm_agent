"""
Sequential Test Cases for Slurm Agent

Tests the agent's ability to:
1. Parse complex/ambiguous user requests
2. Summarize large, complex outputs
3. Handle edge cases and errors
4. Make multi-step reasoning decisions
5. Provide actionable recommendations

Usage:
    # Start mock server first (in another terminal):
    python mock_mcp_server.py --hard
    
    # Then run tests:
    python test_sequential.py
    python test_sequential.py --verbose      # Show detailed output
    python test_sequential.py --category 1   # Run specific category
    python test_sequential.py --test TC1.1   # Run specific test case
"""

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from enum import Enum
from datetime import datetime
import argparse
import traceback

# Import the agent
try:
    from flow.slurm_structured_agent import SlurmStructuredAgent
    from flow.slurm_action import SlurmActionType
except ImportError:
    sys.path.insert(0, '.')
    from flow.slurm_structured_agent import SlurmStructuredAgent
    from flow.slurm_action import SlurmActionType


# ============ Test Configuration ============
class TestStatus(Enum):
    PASSED = "✅ PASSED"
    FAILED = "❌ FAILED"
    SKIPPED = "⏭️ SKIPPED"
    ERROR = "💥 ERROR"


@dataclass
class TestResult:
    """Result of a single test case"""
    test_id: str
    name: str
    status: TestStatus
    duration: float
    input_prompt: str
    expected: str
    actual: str
    details: str = ""
    error: Optional[str] = None


@dataclass
class TestCase:
    """Definition of a test case"""
    id: str
    name: str
    category: int
    description: str
    input_prompt: str
    expected_action: Optional[str] = None  # Expected SlurmActionType or "chat"/"confirm"
    expected_contains: List[str] = field(default_factory=list)  # Keywords expected in response
    expected_not_contains: List[str] = field(default_factory=list)  # Keywords NOT expected
    multi_step: bool = False  # Requires multiple interactions
    follow_up: Optional[str] = None  # Follow-up prompt for multi-step
    validation_fn: Optional[Callable] = None  # Custom validation function


# ============ Test Case Definitions ============

# Category 1: Ambiguous Requests
CATEGORY_1_TESTS = [
    TestCase(
        id="TC1.1",
        name="Vague Job Query",
        category=1,
        description="'stuff' is not a Slurm term - should interpret as squeue",
        input_prompt="what's happening with my stuff",
        expected_action="squeue",
        expected_contains=["job", "queue"],
    ),
    TestCase(
        id="TC1.2",
        name="Implicit GPU Request",
        category=1,
        description="No explicit mention of GPU - should infer GPU requirements",
        input_prompt="I need to run pytorch training",
        expected_action=None,  # Could be sbatch/srun or chat advice
        expected_contains=["gpu", "partition"],
    ),
    TestCase(
        id="TC1.3",
        name="Relative Time Reference",
        category=1,
        description="Must calculate date from 'last week'",
        input_prompt="show me jobs from last week",
        expected_action="sacct",
        expected_contains=["history", "job"],
    ),
    TestCase(
        id="TC1.4",
        name="Compound Request",
        category=1,
        description="Two questions in one request",
        input_prompt="check if the cluster is busy and if I can run a 4-GPU job",
        expected_action="sinfo",
        expected_contains=["gpu", "available", "cluster"],
    ),
    TestCase(
        id="TC1.5",
        name="Slang and Abbreviations",
        category=1,
        description="User uses informal language",
        input_prompt="yo check my q real quick",
        expected_action="squeue",
    ),
    TestCase(
        id="TC1.6",
        name="Typo in Command",
        category=1,
        description="Typo in command name",
        input_prompt="show me sqeue for my jobs",
        expected_action="squeue",
    ),
]

# Category 2: Complex Output Summarization
CATEGORY_2_TESTS = [
    TestCase(
        id="TC2.1",
        name="Large Queue Summary",
        category=2,
        description="Queue with 50+ jobs should be summarized",
        input_prompt="show all jobs in the queue",
        expected_action="squeue",
        expected_contains=["running", "pending"],
    ),
    TestCase(
        id="TC2.2",
        name="Mixed Partition Status",
        category=2,
        description="Partitions with various states including drain/down",
        input_prompt="show cluster status with all partitions",
        expected_action="sinfo",
        expected_contains=["partition", "node"],
    ),
    TestCase(
        id="TC2.3",
        name="Job History with Failures",
        category=2,
        description="History with OOM kills, timeouts, failed jobs",
        input_prompt="show my job history for the past week",
        expected_action="sacct",
        expected_contains=["completed", "failed"],
    ),
    TestCase(
        id="TC2.4",
        name="Node Resource Summary",
        category=2,
        description="Summarize resource utilization across nodes",
        input_prompt="show me available resources on all nodes",
        expected_action="sinfo",
        expected_contains=["cpu", "memory"],
    ),
]

# Category 3: Edge Cases
CATEGORY_3_TESTS = [
    TestCase(
        id="TC3.1",
        name="Empty Queue",
        category=3,
        description="No jobs in queue - should give friendly message",
        input_prompt="show my jobs",
        expected_action="squeue",
        expected_not_contains=["error", "failed"],
    ),
    TestCase(
        id="TC3.2",
        name="All Nodes Down",
        category=3,
        description="All nodes in drain/down state",
        input_prompt="cluster status",
        expected_action="sinfo",
        expected_contains=["down", "unavailable", "drain", "node"],
    ),
    TestCase(
        id="TC3.3",
        name="Resource Exhaustion Request",
        category=3,
        description="Request more GPUs than cluster has",
        input_prompt="submit a job with 100 GPUs",
        expected_contains=["gpu", "available"],
    ),
    TestCase(
        id="TC3.4",
        name="Invalid Job ID",
        category=3,
        description="Job doesn't exist",
        input_prompt="cancel job 99999",
        expected_action="confirm",  # Should still try to confirm cancel
    ),
    TestCase(
        id="TC3.5",
        name="Special Characters in Request",
        category=3,
        description="Request with special chars",
        input_prompt="show job #12345 details",
        expected_action="scontrol_show_job",
    ),
    TestCase(
        id="TC3.6",
        name="Very Long Job Name",
        category=3,
        description="Job name with many characters",
        input_prompt="submit a job named 'this_is_a_very_long_job_name_that_might_cause_issues_in_some_systems_v123'",
        expected_action="sbatch",
    ),
]

# Category 4: Multi-Step Reasoning
CATEGORY_4_TESTS = [
    TestCase(
        id="TC4.1",
        name="Debug Failed Job",
        category=4,
        description="Should identify failed job and explain reason",
        input_prompt="why did my job fail",
        expected_action="sacct",
        expected_contains=["fail", "error", "job"],
    ),
    TestCase(
        id="TC4.2",
        name="Array Job Suggestion",
        category=4,
        description="Should recognize array job opportunity",
        input_prompt="I want to run 100 independent tasks",
        expected_contains=["array"],
    ),
    TestCase(
        id="TC4.3",
        name="GPU Memory Requirement",
        category=4,
        description="Match GPU memory to available hardware",
        input_prompt="I need to train a model that needs 32GB GPU memory",
        expected_contains=["a100", "gpu"],
    ),
    TestCase(
        id="TC4.4",
        name="Job Dependency Setup",
        category=4,
        description="Setting up job dependencies",
        input_prompt="I want to run job B after job A completes successfully",
        expected_contains=["depend", "afterok"],
    ),
]

# Category 5: Error Recovery (Simulated)
CATEGORY_5_TESTS = [
    TestCase(
        id="TC5.1",
        name="Graceful Error Handling",
        category=5,
        description="Handle unexpected responses gracefully",
        input_prompt="show non-existent-partition status",
        expected_action="sinfo",
    ),
    TestCase(
        id="TC5.2",
        name="Ambiguous Cancel Request",
        category=5,
        description="Cancel request without clear job ID",
        input_prompt="cancel the job",
        expected_contains=["which", "job", "id"],
    ),
    TestCase(
        id="TC5.3",
        name="Incomplete Submission",
        category=5,
        description="Job submission without required parameters",
        input_prompt="submit a job",
        expected_contains=["script", "command", "what"],
    ),
]

# Category 6: Realistic Scenarios
CATEGORY_6_TESTS = [
    TestCase(
        id="TC6.1",
        name="New User Onboarding",
        category=6,
        description="First-time user asking for help",
        input_prompt="I'm new here, how do I submit a job?",
        expected_action="chat",
        expected_contains=["sbatch", "script", "submit"],
    ),
    TestCase(
        id="TC6.2",
        name="GPU Job Troubleshooting",
        category=6,
        description="Debug pending GPU job",
        input_prompt="my GPU job has been pending for 2 hours, why?",
        expected_contains=["gpu", "pending", "resource", "queue"],
    ),
    TestCase(
        id="TC6.3",
        name="Batch Processing Advice",
        category=6,
        description="Large-scale processing recommendation",
        input_prompt="I have 1000 files to process, each takes 1 hour. What's the best way?",
        expected_contains=["array"],
    ),
    TestCase(
        id="TC6.4",
        name="Resource Estimation",
        category=6,
        description="Help estimate required resources",
        input_prompt="How much memory should I request for a job that processes 50GB of data?",
        expected_contains=["memory", "mem"],
    ),
    TestCase(
        id="TC6.5",
        name="Priority Explanation",
        category=6,
        description="Explain job priority system",
        input_prompt="why is my job low priority?",
        expected_contains=["priority", "fair", "share"],
    ),
]

# Category 7: Dangerous Commands (Confirmation Flow)
CATEGORY_7_TESTS = [
    TestCase(
        id="TC7.1",
        name="Cancel Job Confirmation",
        category=7,
        description="Dangerous command should ask for confirmation",
        input_prompt="cancel job 12345",
        expected_action="confirm",
        expected_contains=["confirm", "sure", "cancel"],
        multi_step=True,
        follow_up="yes, cancel it",
    ),
    TestCase(
        id="TC7.2",
        name="Hold Job Confirmation",
        category=7,
        description="Hold command should ask for confirmation",
        input_prompt="hold job 12345",
        expected_action="confirm",
        expected_contains=["confirm", "hold"],
    ),
    TestCase(
        id="TC7.3",
        name="Cancel Declined",
        category=7,
        description="User declines dangerous action",
        input_prompt="cancel job 12345",
        expected_action="confirm",
        multi_step=True,
        follow_up="no, don't cancel",
    ),
    TestCase(
        id="TC7.4",
        name="Requeue Confirmation",
        category=7,
        description="Requeue is dangerous - restarts job",
        input_prompt="requeue job 12345",
        expected_action="confirm",
        expected_contains=["requeue", "restart", "confirm"],
    ),
]

# Combine all categories
ALL_TEST_CASES = (
    CATEGORY_1_TESTS +
    CATEGORY_2_TESTS +
    CATEGORY_3_TESTS +
    CATEGORY_4_TESTS +
    CATEGORY_5_TESTS +
    CATEGORY_6_TESTS +
    CATEGORY_7_TESTS
)


# ============ Test Runner ============
class SequentialTestRunner:
    """Runs test cases sequentially and collects results"""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.results: List[TestResult] = []
        self.agent: Optional[SlurmStructuredAgent] = None
        
        # Setup logging
        level = logging.DEBUG if verbose else logging.WARNING
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
    
    async def setup(self):
        """Initialize the agent"""
        print("\n🔧 Setting up Slurm Agent...")
        self.agent = SlurmStructuredAgent()
        await self.agent.connect()
        print("✅ Agent connected to MCP server\n")
    
    async def teardown(self):
        """Cleanup resources"""
        if self.agent:
            await self.agent.disconnect()
            print("\n🧹 Agent disconnected")
    
    async def run_single_test(self, test: TestCase) -> TestResult:
        """Run a single test case"""
        start_time = time.time()
        
        try:
            print(f"\n{'='*60}")
            print(f"🧪 {test.id}: {test.name}")
            print(f"   Category: {test.category}")
            print(f"   Input: \"{test.input_prompt}\"")
            
            if self.verbose:
                print(f"   Description: {test.description}")
                print(f"   Expected Action: {test.expected_action}")
                print(f"   Expected Contains: {test.expected_contains}")
            
            # Run the agent
            full_response = ""
            decision_type = None
            action_type = None
            
            async for chunk in self.agent.process_request_stream(test.input_prompt):
                if isinstance(chunk, dict):
                    if "decision" in chunk:
                        decision_type = chunk.get("decision")
                        if chunk.get("action"):
                            action_type = chunk["action"].get("action")
                    if "content" in chunk:
                        full_response += chunk["content"]
                elif isinstance(chunk, str):
                    full_response += chunk
            
            duration = time.time() - start_time
            
            # Determine actual action for comparison
            actual_action = decision_type if decision_type in ["chat", "confirm", "cancel"] else action_type
            
            if self.verbose:
                print(f"\n   📝 Response preview: {full_response[:200]}...")
                print(f"   🎯 Decision: {decision_type}, Action: {action_type}")
            
            # Validate results
            passed = True
            details = []
            
            # Check expected action
            if test.expected_action:
                if actual_action != test.expected_action:
                    # Allow partial matches for action types
                    if not (actual_action and test.expected_action in str(actual_action)):
                        passed = False
                        details.append(f"Action mismatch: expected '{test.expected_action}', got '{actual_action}'")
            
            # Check expected keywords in response
            response_lower = full_response.lower()
            for keyword in test.expected_contains:
                if keyword.lower() not in response_lower:
                    passed = False
                    details.append(f"Missing keyword: '{keyword}'")
            
            # Check keywords that should NOT be present
            for keyword in test.expected_not_contains:
                if keyword.lower() in response_lower:
                    passed = False
                    details.append(f"Unexpected keyword found: '{keyword}'")
            
            status = TestStatus.PASSED if passed else TestStatus.FAILED
            print(f"   {status.value} ({duration:.2f}s)")
            
            if details:
                for detail in details:
                    print(f"      ⚠️ {detail}")
            
            return TestResult(
                test_id=test.id,
                name=test.name,
                status=status,
                duration=duration,
                input_prompt=test.input_prompt,
                expected=f"action={test.expected_action}, contains={test.expected_contains}",
                actual=f"action={actual_action}, response_len={len(full_response)}",
                details="; ".join(details),
            )
            
        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"{type(e).__name__}: {str(e)}"
            print(f"   💥 ERROR: {error_msg}")
            
            if self.verbose:
                traceback.print_exc()
            
            return TestResult(
                test_id=test.id,
                name=test.name,
                status=TestStatus.ERROR,
                duration=duration,
                input_prompt=test.input_prompt,
                expected=f"action={test.expected_action}",
                actual="ERROR",
                error=error_msg,
            )
    
    async def run_multi_step_test(self, test: TestCase) -> TestResult:
        """Run a multi-step test with follow-up"""
        start_time = time.time()
        
        try:
            print(f"\n{'='*60}")
            print(f"🧪 {test.id}: {test.name} (Multi-Step)")
            print(f"   Step 1: \"{test.input_prompt}\"")
            
            # Step 1: Initial request
            full_response_1 = ""
            async for chunk in self.agent.process_request_stream(test.input_prompt):
                if isinstance(chunk, dict):
                    if "content" in chunk:
                        full_response_1 += chunk["content"]
                elif isinstance(chunk, str):
                    full_response_1 += chunk
            
            print(f"   Step 1 Response: {full_response_1[:100]}...")
            
            # Step 2: Follow-up
            if test.follow_up:
                print(f"   Step 2: \"{test.follow_up}\"")
                
                full_response_2 = ""
                async for chunk in self.agent.process_request_stream(test.follow_up):
                    if isinstance(chunk, dict):
                        if "content" in chunk:
                            full_response_2 += chunk["content"]
                    elif isinstance(chunk, str):
                        full_response_2 += chunk
                
                print(f"   Step 2 Response: {full_response_2[:100]}...")
            
            duration = time.time() - start_time
            
            # Basic validation - check confirmation flow worked
            passed = True
            details = []
            
            combined_response = full_response_1.lower()
            for keyword in test.expected_contains:
                if keyword.lower() not in combined_response:
                    passed = False
                    details.append(f"Missing keyword in step 1: '{keyword}'")
            
            status = TestStatus.PASSED if passed else TestStatus.FAILED
            print(f"   {status.value} ({duration:.2f}s)")
            
            return TestResult(
                test_id=test.id,
                name=test.name,
                status=status,
                duration=duration,
                input_prompt=f"{test.input_prompt} -> {test.follow_up}",
                expected=str(test.expected_contains),
                actual=f"step1_len={len(full_response_1)}",
                details="; ".join(details),
            )
            
        except Exception as e:
            duration = time.time() - start_time
            return TestResult(
                test_id=test.id,
                name=test.name,
                status=TestStatus.ERROR,
                duration=duration,
                input_prompt=test.input_prompt,
                expected="multi-step",
                actual="ERROR",
                error=str(e),
            )
    
    async def run_tests(
        self,
        tests: List[TestCase],
        category: Optional[int] = None,
        test_id: Optional[str] = None,
    ) -> List[TestResult]:
        """Run multiple tests"""
        
        # Filter tests if needed
        if test_id:
            tests = [t for t in tests if t.id == test_id]
        elif category:
            tests = [t for t in tests if t.category == category]
        
        if not tests:
            print("❌ No tests match the filter criteria")
            return []
        
        print(f"\n🚀 Running {len(tests)} test(s)...")
        print("=" * 60)
        
        await self.setup()
        
        try:
            for test in tests:
                if test.multi_step:
                    result = await self.run_multi_step_test(test)
                else:
                    result = await self.run_single_test(test)
                
                self.results.append(result)
                
                # Small delay between tests
                await asyncio.sleep(0.5)
        
        finally:
            await self.teardown()
        
        return self.results
    
    def print_summary(self):
        """Print test results summary"""
        print("\n")
        print("=" * 60)
        print("📊 TEST RESULTS SUMMARY")
        print("=" * 60)
        
        passed = sum(1 for r in self.results if r.status == TestStatus.PASSED)
        failed = sum(1 for r in self.results if r.status == TestStatus.FAILED)
        errors = sum(1 for r in self.results if r.status == TestStatus.ERROR)
        skipped = sum(1 for r in self.results if r.status == TestStatus.SKIPPED)
        total = len(self.results)
        
        print(f"\n  Total:   {total}")
        print(f"  ✅ Passed:  {passed}")
        print(f"  ❌ Failed:  {failed}")
        print(f"  💥 Errors:  {errors}")
        print(f"  ⏭️ Skipped: {skipped}")
        
        if total > 0:
            success_rate = (passed / total) * 100
            print(f"\n  Success Rate: {success_rate:.1f}%")
        
        # Show failed tests
        if failed > 0 or errors > 0:
            print("\n❌ Failed/Error Tests:")
            for r in self.results:
                if r.status in [TestStatus.FAILED, TestStatus.ERROR]:
                    print(f"  • {r.test_id}: {r.name}")
                    if r.details:
                        print(f"    Details: {r.details}")
                    if r.error:
                        print(f"    Error: {r.error}")
        
        # Timing stats
        total_time = sum(r.duration for r in self.results)
        print(f"\n⏱️ Total Time: {total_time:.2f}s")
        
        print("=" * 60)
    
    def export_results(self, filepath: str = "test_results.json"):
        """Export results to JSON file"""
        results_data = [
            {
                "test_id": r.test_id,
                "name": r.name,
                "status": r.status.name,
                "duration": r.duration,
                "input": r.input_prompt,
                "expected": r.expected,
                "actual": r.actual,
                "details": r.details,
                "error": r.error,
            }
            for r in self.results
        ]
        
        with open(filepath, "w") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "total_tests": len(self.results),
                "passed": sum(1 for r in self.results if r.status == TestStatus.PASSED),
                "failed": sum(1 for r in self.results if r.status == TestStatus.FAILED),
                "results": results_data,
            }, f, indent=2)
        
        print(f"\n📁 Results exported to {filepath}")


# ============ Main Entry Point ============
async def main():
    parser = argparse.ArgumentParser(description="Sequential Test Runner for Slurm Agent")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    parser.add_argument("--category", "-c", type=int, help="Run tests from specific category (1-7)")
    parser.add_argument("--test", "-t", type=str, help="Run specific test by ID (e.g., TC1.1)")
    parser.add_argument("--export", "-e", type=str, help="Export results to JSON file")
    parser.add_argument("--list", "-l", action="store_true", help="List all test cases")
    
    args = parser.parse_args()
    
    # List mode
    if args.list:
        print("\n📋 Available Test Cases:")
        print("=" * 60)
        current_category = 0
        for test in ALL_TEST_CASES:
            if test.category != current_category:
                current_category = test.category
                print(f"\n📁 Category {current_category}:")
            print(f"  {test.id}: {test.name}")
        print()
        return
    
    # Run tests
    runner = SequentialTestRunner(verbose=args.verbose)
    
    try:
        await runner.run_tests(
            ALL_TEST_CASES,
            category=args.category,
            test_id=args.test,
        )
    except KeyboardInterrupt:
        print("\n\n⚠️ Tests interrupted by user")
    
    runner.print_summary()
    
    if args.export:
        runner.export_results(args.export)
    else:
        runner.export_results()  # Default filename


if __name__ == "__main__":
    asyncio.run(main())
