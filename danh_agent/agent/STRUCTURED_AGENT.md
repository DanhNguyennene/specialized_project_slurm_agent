# Structured Slurm Agent Architecture

## Overview

The Structured Slurm Agent uses OpenAI's **structured outputs** feature with Pydantic models instead of traditional function calling. The agent generates complete command sequences as JSON, which are then executed by a builder pattern.

## Architecture

### 1. Pydantic Command Models (`utils/slurm_commands.py`)

Each Slurm command is defined as a Pydantic `BaseModel`:

```python
class SbatchCommand(BaseModel):
    command_type: Literal["sbatch"] = "sbatch"
    script_path: str
    command: str
    job_name: Optional[str] = None
    partition: Optional[str] = None
    # ... more parameters
```

**Benefits:**
- Type safety and validation
- Clear schema for agent
- Easy serialization/deserialization
- IDE autocomplete support

### 2. Command Sequence Model

The agent outputs a `SlurmCommandSequence`:

```python
class SlurmCommandSequence(BaseModel):
    description: str  # What this accomplishes
    commands: List[SlurmCommand]  # Ordered commands
    reason: Optional[str]  # Why needed
    expected_outcome: Optional[str]  # What to expect
```

### 3. Command Builder Pattern

`SlurmCommandBuilder` executes sequences:

```python
builder = SlurmCommandBuilder(connection)
results = await builder.execute_sequence(sequence)
summary = builder.get_summary()
```

### 4. Structured Agent

`SlurmStructuredAgent` generates command sequences using `chat_structured()`:

```python
agent = SlurmStructuredAgent()

# Generate plan only
result = await agent.plan_only("Submit training job")

# Generate and execute
result = await agent.run("Submit training job", execute=True)

# Execute pre-approved plan
result = await agent.execute_sequence(sequence)
```

## Advantages Over Function Calling

### Traditional Function Calling
- Agent calls tools one at a time
- Multiple LLM round-trips
- Harder to review before execution
- Difficult to parallelize
- No built-in execution plan

### Structured Outputs
- ✅ Agent generates complete plan upfront
- ✅ Single LLM call per request
- ✅ Easy to review/approve before execution
- ✅ Can optimize execution order
- ✅ Clear execution plan with reasoning
- ✅ Better error handling across sequence
- ✅ Can retry entire sequence if needed

## API Endpoints

### 1. Plan Only (`POST /slurm/plan`)

Generate command sequence without execution:

```bash
curl -X POST http://localhost:20000/slurm/plan \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Submit a training job and check its status"
  }'
```

**Response:**
```json
{
  "success": true,
  "sequence": {
    "description": "Submit training job and monitor status",
    "commands": [
      {
        "command_type": "sbatch",
        "script_path": "/tmp/train.sh",
        "command": "python train.py",
        "job_name": "training",
        ...
      },
      {
        "command_type": "squeue",
        "user": "myuser",
        ...
      }
    ],
    "reason": "User wants to train model and check status",
    "expected_outcome": "Job submitted and currently running"
  },
  "plan_message": "**Plan: Submit training job...**\n...",
  "note": "Review the plan and use /slurm/approve to execute"
}
```

### 2. Direct Execution (`POST /slurm/execute`)

Generate and execute in one call:

```bash
curl -X POST http://localhost:20000/slurm/execute \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Check all running jobs"
  }'
```

**Response:**
```json
{
  "success": true,
  "sequence": { ... },
  "executed": true,
  "execution_summary": {
    "total_commands": 2,
    "successful": 2,
    "failed": 0
  },
  "execution_results": [
    {
      "step": 1,
      "command": "squeue",
      "result": { ... },
      "success": true
    }
  ],
  "message": "**Executed: Check all running jobs**\n✓ Step 1: squeue\n..."
}
```

### 3. Approve and Execute (`POST /slurm/approve`)

Execute pre-generated plan:

```bash
curl -X POST http://localhost:20000/slurm/approve \
  -H "Content-Type: application/json" \
  -d '{
    "sequence": {
      "description": "...",
      "commands": [...]
    }
  }'
```

## Workflow Examples

### Workflow 1: Review Before Execution

```python
# Step 1: Generate plan
plan_result = await agent.plan_only("Submit 3 training jobs")

# Step 2: Review
print(plan_result["plan_message"])
# User reviews the plan...

# Step 3: Approve and execute
sequence = SlurmCommandSequence(**plan_result["sequence"])
exec_result = await agent.execute_sequence(sequence)
```

### Workflow 2: Direct Execution

```python
# One-shot: generate and execute
result = await agent.run(
    "Cancel all pending jobs for user bob",
    execute=True
)

print(result["execution_summary"])
```

### Workflow 3: API Integration

```python
import httpx

async with httpx.AsyncClient() as client:
    # Generate plan
    plan_resp = await client.post(
        "http://localhost:20000/slurm/plan",
        json={"message": "Submit job"}
    )
    
    # Review plan
    plan_data = plan_resp.json()
    print(plan_data["plan_message"])
    
    # Approve if satisfied
    if user_approves():
        exec_resp = await client.post(
            "http://localhost:20000/slurm/approve",
            json={"sequence": plan_data["sequence"]}
        )
```

## Command Types

All 12 Slurm commands are supported:

| Command | Description | Key Parameters |
|---------|-------------|----------------|
| `sbatch` | Submit batch job | script_path, command, job_name, partition, resources |
| `squeue` | Query job queue | user, job_id, partition, state |
| `scancel` | Cancel jobs | job_id, user, partition, state |
| `sinfo` | View cluster info | partition, nodes, summarize |
| `sacct` | View job history | job_id, user, start_time, end_time, state |
| `scontrol_show` | Show details | entity (job/node/partition), name |
| `srun` | Run interactive | command, nodes, ntasks, partition, timeout |
| `scontrol_update` | Update properties | entity_type, entity_id, properties |
| `scontrol_hold` | Hold job | job_id |
| `scontrol_release` | Release job | job_id |
| `sprio` | View priorities | job_id, user |
| `sshare` | View fair-share | account, user |

## Error Handling

### Execution Errors

The builder handles errors gracefully:

```python
results = await builder.execute_sequence(sequence)

for result in results:
    if not result["success"]:
        print(f"Step {result['step']} failed: {result['error']}")
```

### Ignorable Errors

Some errors don't stop execution:
- "no jobs found"
- "already cancelled"
- "already completed"

### Critical Errors

Critical errors stop the sequence immediately.

## Testing

Run the test suite:

```bash
cd /mnt/e/workspace/uni/specialized_project/danh_agent/agent
python test_structured_agent.py
```

Tests cover:
1. Manual sequence creation
2. Agent-generated sequences
3. Full workflow (plan -> review -> execute)
4. Direct execution
5. Complex multi-command scenarios

## Migration Guide

### From Function Calling

**Before (Function Calling):**
```python
agent = SlurmAgent()
result = await agent.run("Submit job")
# Agent calls sbatch tool
# Agent calls squeue tool
# Multiple LLM calls
```

**After (Structured Outputs):**
```python
agent = SlurmStructuredAgent()
result = await agent.run("Submit job", execute=True)
# Agent generates complete plan (1 LLM call)
# Builder executes all commands
# Single structured response
```

### Key Differences

| Aspect | Function Calling | Structured Outputs |
|--------|-----------------|-------------------|
| LLM calls | Multiple (per tool) | Single (per request) |
| Planning | Implicit | Explicit (visible) |
| Review | Hard (mid-execution) | Easy (before execution) |
| Execution | Sequential forced | Optimizable |
| Error handling | Per-tool | Per-sequence |
| Approval workflow | Not built-in | Natural fit |

## Best Practices

### 1. Use Plan-Review-Execute for Critical Tasks

```python
# Generate plan
plan = await agent.plan_only("Delete all jobs")

# Show user
print(plan["plan_message"])

# Get approval
if confirm("Execute this plan?"):
    await agent.execute_sequence(
        SlurmCommandSequence(**plan["sequence"])
    )
```

### 2. Direct Execution for Safe Operations

```python
# Safe operations can execute directly
await agent.run("Show cluster info", execute=True)
```

### 3. Custom Validation

```python
plan = await agent.plan_only(message)

# Custom checks
sequence = SlurmCommandSequence(**plan["sequence"])
if any(cmd.command_type == "scancel" for cmd in sequence.commands):
    # Require extra confirmation for cancellations
    pass
```

### 4. Logging and Audit

```python
result = await agent.run(message, execute=True)

# Log execution
audit_log.write({
    "user": current_user,
    "request": message,
    "sequence": result["sequence"],
    "summary": result["execution_summary"],
    "timestamp": datetime.now()
})
```

## Configuration

### Agent Settings

```python
agent = SlurmStructuredAgent(
    model="qwen2.5:7b",       # Model to use
    base_url="http://localhost:11434/v1",
    temperature=0.0,           # Deterministic output
    max_retries=3             # Retry on failure
)
```

### Connection Management

```python
# Manual connection control
async with agent:
    # Connection automatically managed
    result = await agent.run(message)
# Connection closed

# Or manage explicitly
await agent.connection.connect()
try:
    result = await agent.run(message)
finally:
    await agent.connection.disconnect()
```

## Performance

### Benchmarks

| Metric | Function Calling | Structured Outputs |
|--------|-----------------|-------------------|
| Avg LLM calls per task | 3-5 | 1 |
| Planning visibility | Low | High |
| Execution control | Limited | Full |
| Error recovery | Per-tool | Per-sequence |
| Approval workflow | Complex | Simple |

### When to Use Each

**Function Calling:**
- Simple single-command tasks
- Real-time interactive sessions
- Streaming responses needed
- Legacy compatibility

**Structured Outputs:**
- Multi-step workflows
- Critical operations needing review
- Batch processing
- Audit/compliance requirements
- Complex task planning

## Future Enhancements

1. **Parallel Execution**: Execute independent commands simultaneously
2. **Dependencies**: Specify command dependencies in sequence
3. **Conditional Execution**: Skip commands based on results
4. **Rollback**: Automatic rollback on failure
5. **Caching**: Cache frequently used sequences
6. **Templates**: Pre-defined sequence templates

## Troubleshooting

### Issue: Sequence Generation Fails

**Solution:** Check model supports structured outputs (needs function calling capability)

### Issue: Execution Fails on First Command

**Solution:** Verify Slurm connection is established:
```python
if not agent.connection.connected:
    await agent.connection.connect()
```

### Issue: Invalid Command Parameters

**Solution:** Pydantic validation will catch this. Check error details:
```python
try:
    sequence = SlurmCommandSequence(**data)
except ValidationError as e:
    print(e.errors())
```

## Conclusion

The structured outputs approach provides:
- ✅ Better planning visibility
- ✅ Easier approval workflows
- ✅ Fewer LLM calls
- ✅ More control over execution
- ✅ Better error handling
- ✅ Clearer audit trail

Perfect for production Slurm management where safety and visibility matter.
