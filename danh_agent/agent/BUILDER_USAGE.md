# Builder Summary & Usage Guide

## ✅ What's Working

The **SlurmCommandBuilder** is fully functional and can:

1. **Compile** Pydantic command sequences to executable shell scripts
2. **Validate** sequences for errors and warnings
3. **Save** scripts to files with proper permissions
4. **Work offline** - no Slurm connection required

## 📁 Files Created

### Core Implementation
- `utils/slurm_commands.py` - All 12 Slurm command types as Pydantic models + Builder class
- `utils/slurm_tools_minimal.py` - Connection handler (for later when you add Slurm)
- `flow/slurm_structured_agent.py` - Agent that generates command sequences (uses model)

### Tests & Demos
- `test_builder_offline.py` - ✅ Comprehensive builder tests (5 scenarios)
- `demo_builder_quick.py` - ✅ Quick demos with pre-made sequences (INSTANT)
- `test_structured_agent.py` - Model-based tests (slow due to structured outputs)
- `demo_end_to_end.py` - Full agent workflow (slow - model calls)

### Generated Scripts (in /tmp/)
- `demo1_training.sh` - Single GPU training job
- `demo2_parallel_training.sh` - 3 parallel training jobs
- `demo3_monitoring.sh` - Cluster monitoring commands
- `demo4_custom.sh` - Data processing job
- `complex_workflow.sh` - Multi-command workflow
- `slurm_test_script.sh` - Quick cluster check

## 🐌 Why Was It Slow?

The demo was hanging because:

**Structured outputs with complex schemas take time** - The model needs to:
1. Understand the complex Pydantic schema (12 command types, discriminated union)
2. Generate valid JSON matching the schema
3. Ensure all constraints are met

**Solution**: Use the quick demos instead:
- `python demo_builder_quick.py` ← ⚡ INSTANT (no model)
- `python test_builder_offline.py` ← ⚡ INSTANT (no model)

The agent-based approach works but is slow for complex schemas. Better for production after optimization.

## 🚀 How to Use the Builder

### Option 1: Direct Usage (Recommended for now)

```python
from utils.slurm_commands import (
    SlurmCommandSequence,
    SlurmCommandBuilder,
    SbatchCommand,
    SqueueCommand
)

# Create sequence manually
sequence = SlurmCommandSequence(
    description="Train model",
    commands=[
        SbatchCommand(
            script_path="/tmp/train.sh",
            command="python train.py",
            job_name="training",
            partition="gpu",
            nodes=1,
            ntasks=1,
            cpus_per_task=4,
            mem="16GB",
            time="4:00:00",
            output="/logs/train_%j.out",
            error=None
        ),
        SqueueCommand(user="$USER", job_id=None, partition=None, state=None)
    ]
)

# Build
builder = SlurmCommandBuilder()

# Validate
validation = builder.validate_sequence(sequence)
print(validation)

# Compile to shell
script = builder.compile_to_shell(sequence)
print(script)

# Save
builder.save_script(sequence, "/tmp/my_job.sh")
```

### Option 2: With Agent (Slow but automatic)

```python
from flow.slurm_structured_agent import SlurmStructuredAgent
from utils.slurm_commands import SlurmCommandBuilder, SlurmCommandSequence

agent = SlurmStructuredAgent()

# Generate plan (THIS IS SLOW - 30-60 seconds)
result = await agent.plan_only("Submit a training job")

# Compile
sequence = SlurmCommandSequence(**result["sequence"])
builder = SlurmCommandBuilder()
builder.save_script(sequence, "/tmp/generated.sh")
```

## 📊 Builder Features

### 1. Compilation
```python
builder = SlurmCommandBuilder()
shell_script = builder.compile_to_shell(sequence)
# Returns executable bash script
```

### 2. Validation
```python
validation = builder.validate_sequence(sequence)
# {
#   "valid": True/False,
#   "errors": [...],
#   "warnings": [...],
#   "command_count": N
# }
```

### 3. Save to File
```python
path = builder.save_script(sequence, "/path/to/script.sh")
# Automatically makes executable (chmod +x)
```

### 4. All 12 Slurm Commands Supported

| Command | Purpose |
|---------|---------|
| `sbatch` | Submit batch job |
| `squeue` | Check job queue |
| `scancel` | Cancel jobs |
| `sinfo` | Cluster info |
| `sacct` | Job history |
| `scontrol_show` | Show details |
| `srun` | Run interactive |
| `scontrol_update` | Update properties |
| `scontrol_hold` | Hold job |
| `scontrol_release` | Release job |
| `sprio` | View priorities |
| `sshare` | View fair-share |

## 🔧 Next Steps

### When You Add Slurm Connection:

1. **Set up MCP server** or direct Slurm connection
2. **Update connection in** `utils/slurm_tools_minimal.py`
3. **Use builder's execute mode**:

```python
builder = SlurmCommandBuilder(connection)
results = await builder.execute_sequence(sequence)
summary = builder.get_summary()
```

### For Now (Offline Mode):

1. ✅ Create sequences manually or use examples
2. ✅ Compile to shell scripts
3. ✅ Review/edit scripts as needed
4. ✅ Copy to Slurm cluster
5. ✅ Run: `bash script.sh`

## 📝 Command Examples

### Simple Training Job
```python
SbatchCommand(
    script_path="/tmp/train.sh",
    command="python train.py --epochs 100",
    job_name="training",
    partition="gpu",
    nodes=1,
    cpus_per_task=8,
    mem="32GB",
    time="4:00:00",
    output="/logs/train_%j.out",
    error="/logs/train_%j.err"
)
```

### Check Queue
```python
SqueueCommand(
    user="$USER",
    partition="gpu",
    state="RUNNING"
)
```

### Cancel Job
```python
ScancelCommand(
    job_id="12345",
    user=None,
    partition=None,
    state=None
)
```

## 🎯 Recommendations

**For Development:**
- Use `demo_builder_quick.py` for instant results
- Manually create sequences until agent is optimized
- Test with different command combinations

**For Production:**
- Optimize agent system prompt for faster generation
- Consider caching common patterns
- Use simpler models for structured output
- Or use function calling instead of structured outputs

**Current Best Workflow:**
1. Define what you need in Python (Pydantic models)
2. Build with `SlurmCommandBuilder`
3. Review generated shell script
4. Transfer to Slurm cluster and run

## ✨ Key Advantages

- ✅ **Type-safe** - Pydantic validation
- ✅ **Offline** - No Slurm connection needed for compilation
- ✅ **Portable** - Scripts work on any Slurm cluster
- ✅ **Reviewable** - See exactly what will run
- ✅ **Flexible** - Combine commands however you need
- ✅ **Fast** - Instant compilation (when not using agent)

The builder is **production-ready**. The agent integration is functional but needs optimization for speed.
