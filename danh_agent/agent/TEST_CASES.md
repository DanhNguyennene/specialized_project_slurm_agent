# Slurm Agent Hard Test Cases

## Overview
These test cases challenge the agent's ability to:
1. Parse complex/ambiguous user requests
2. Summarize large, complex outputs
3. Handle edge cases and errors
4. Make multi-step reasoning decisions
5. Provide actionable recommendations

---

## Category 1: Ambiguous Requests

### TC1.1: Vague Job Query
**Input:** "what's happening with my stuff"
**Expected:** Agent should interpret as squeue for current user's jobs
**Challenge:** "stuff" is not a Slurm term

### TC1.2: Implicit GPU Request  
**Input:** "I need to run pytorch training"
**Expected:** Agent should infer GPU requirements, suggest appropriate partition
**Challenge:** No explicit mention of GPU or resources

### TC1.3: Relative Time Reference
**Input:** "show me jobs from last week"
**Expected:** sacct with calculated date range
**Challenge:** Must calculate date from "last week"

### TC1.4: Compound Request
**Input:** "check if the cluster is busy and if I can run a 4-GPU job"
**Expected:** Should run sinfo AND provide analysis
**Challenge:** Two questions in one

---

## Category 2: Complex Output Summarization

### TC2.1: Large Queue (50+ jobs)
**Mock Data:** Queue with 50 jobs in various states
**Expected Summary Should Include:**
- Total jobs by state (running/pending/failed)
- Jobs waiting longest
- Resource bottlenecks
- User's position in queue

### TC2.2: Mixed Partition Status
**Mock Data:** Partitions with various states (drain, down, mixed)
**Expected Summary Should Include:**
- Available vs unavailable partitions
- GPU availability specifically
- Maintenance warnings
- Recommendations for which partition to use

### TC2.3: Job History with Failures
**Mock Data:** Job history with OOM kills, timeouts, failed jobs
**Expected Summary Should Include:**
- Success rate
- Common failure patterns
- Resource suggestions based on failures

---

## Category 3: Edge Cases

### TC3.1: Empty Queue
**Input:** "show my jobs"
**Mock Data:** No jobs in queue
**Expected:** Friendly message, not just "no results"

### TC3.2: All Nodes Down
**Input:** "cluster status"
**Mock Data:** All nodes in drain/down state
**Expected:** Clear warning, suggest contacting admin

### TC3.3: Resource Exhaustion
**Input:** "submit a job with 100 GPUs"
**Mock Data:** Only 16 GPUs in cluster
**Expected:** Explain limitation, suggest alternatives

### TC3.4: Invalid Job ID
**Input:** "cancel job 99999"
**Mock Data:** Job doesn't exist
**Expected:** Clear error, suggest checking job ID

---

## Category 4: Multi-Step Reasoning

### TC4.1: Debug Failed Job
**Input:** "why did my job fail"
**Expected Flow:**
1. Get recent jobs (sacct)
2. Identify failed job
3. Get detailed info (scontrol show job)
4. Analyze and explain failure reason

### TC4.2: Optimize Job Submission
**Input:** "I want to run 100 independent tasks"
**Expected:**
- Recognize array job opportunity
- Suggest appropriate syntax
- Warn about queue limits

### TC4.3: Resource Planning
**Input:** "I need to train a model that needs 32GB GPU memory"
**Expected:**
- Check available GPU types (sinfo)
- Identify which GPUs have 32GB+ (A100, etc.)
- Suggest correct partition and gres syntax

---

## Category 5: Error Recovery

### TC5.1: Connection Failure
**Mock:** MCP returns connection error
**Expected:** Graceful degradation, suggest retry

### TC5.2: Timeout
**Mock:** Command takes too long
**Expected:** Inform user, suggest alternative

### TC5.3: Permission Denied
**Mock:** User lacks permissions
**Expected:** Explain what permission is needed

---

## Category 6: Realistic Scenarios

### TC6.1: New User Onboarding
**Input:** "I'm new here, how do I submit a job?"
**Expected:** 
- Explain sbatch basics
- Show cluster partitions
- Provide example script
- Mention documentation

### TC6.2: GPU Job Troubleshooting
**Input:** "my GPU job has been pending for 2 hours"
**Expected:**
- Check job status and reason
- Check GPU availability
- Explain why it's waiting
- Suggest alternatives (different partition, fewer GPUs)

### TC6.3: Batch Processing Workflow
**Input:** "I have 1000 files to process, each takes 1 hour"
**Expected:**
- Recommend array job
- Calculate optimal array size
- Consider time limits
- Warn about fair share impact

---

## Test Data Requirements

### Large Queue Data (TC2.1)
- 50+ jobs
- Mix of states: RUNNING, PENDING, FAILED, COMPLETING
- Various users (to test filtering)
- Different priorities
- Long-waiting jobs (24+ hours pending)

### Complex Partition Data (TC2.2)
- Multiple partitions with different purposes
- Nodes in mixed states
- GPU partitions with allocation info
- Maintenance partition in drain

### Job History Data (TC2.3)
- Jobs with various exit codes
- OOM kills (exit code 137)
- Timeouts (exit code timeout)
- Successful completions
- Different resource usage patterns

---

## Evaluation Criteria

### Accuracy
- Does the agent pick the correct command?
- Are parameters set correctly?

### Completeness
- Does the summary cover all important points?
- Are recommendations provided when appropriate?

### Clarity
- Is the output easy to understand?
- Are technical terms explained?

### Robustness
- Does it handle errors gracefully?
- Does it recover from edge cases?

### Efficiency
- Is the response concise?
- Does it avoid unnecessary commands?

---

## Running Tests

### Quick Start

```bash
# Terminal 1: Start mock server with specific scenario
python mock_mcp_server.py                    # Normal mode
python mock_mcp_server.py --hard             # Hard test mode (50+ jobs)
python mock_mcp_server.py --scenario empty   # Empty queue scenario
python mock_mcp_server.py --scenario down    # All nodes down scenario
python mock_mcp_server.py --scenario busy    # Cluster fully busy
python mock_mcp_server.py --scenario failed  # Many failed jobs (for debugging tests)

# Terminal 2: Run sequential tests
python test_sequential.py                    # Run all tests
python test_sequential.py --verbose          # Show detailed output
python test_sequential.py --category 1       # Run Category 1 (Ambiguous Requests)
python test_sequential.py --test TC1.1       # Run specific test
python test_sequential.py --list             # List all available tests
python test_sequential.py --export results.json  # Export to custom file
```

### Available Scenarios

| Scenario | Description | Use Case |
|----------|-------------|----------|
| `normal` | Default test data (3 jobs, 4 nodes) | Basic functionality testing |
| `hard` | Complex data (55+ jobs, 15 nodes) | Stress testing, summarization |
| `empty` | No jobs in queue | TC3.1: Empty queue handling |
| `down` | All nodes DOWN/DRAIN | TC3.2: Cluster unavailable |
| `busy` | Cluster fully allocated | TC3.3: Resource exhaustion |
| `failed` | Many failed jobs in history | TC4.1: Debug failed jobs |

### Test Categories

| Category | Tests | Description |
|----------|-------|-------------|
| 1 | TC1.1 - TC1.6 | Ambiguous Requests |
| 2 | TC2.1 - TC2.4 | Complex Output Summarization |
| 3 | TC3.1 - TC3.6 | Edge Cases |
| 4 | TC4.1 - TC4.4 | Multi-Step Reasoning |
| 5 | TC5.1 - TC5.3 | Error Recovery |
| 6 | TC6.1 - TC6.5 | Realistic Scenarios |
| 7 | TC7.1 - TC7.4 | Dangerous Commands (Confirmation) |

### Manual API Testing

```bash
# Start the main server
python main.py

# Test via curl
curl -X POST http://localhost:20000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"show my jobs"}],"stream":false}'
```
