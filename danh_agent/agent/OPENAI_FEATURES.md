# Enhanced OpenAI Client - Feature Documentation

## Overview

The enhanced `OllamaClient` now supports **all major OpenAI API features**, enabling powerful capabilities for local LLM interactions through Ollama.

## Key Features Implemented

### 1. **Structured Outputs with Pydantic** ✅
- Define response schemas using Pydantic models
- Guaranteed JSON schema adherence with `strict: true`
- Type-safe responses with automatic validation

**Example:**
```python
from pydantic import BaseModel

class JobInfo(BaseModel):
    job_name: str
    num_tasks: int
    time_limit: str

result = await client.chat_structured(
    messages=[{"role": "user", "content": "Create job config"}],
    response_format=JobInfo
)
```

### 2. **Parallel Tool Calls** ✅
- Execute multiple functions simultaneously
- Configurable via `parallel_tool_calls=True/False`
- Reduces latency for multi-command operations

**Example:**
```python
result = await client.chat_with_tools(
    messages=[{"role": "user", "content": "Check job 123 and 456"}],
    tools=tools,
    parallel_tool_calls=True  # Execute both checks at once
)
```

### 3. **Advanced Streaming** ✅
- Stream responses with delta accumulation
- Stream tool call arguments in real-time
- Progress tracking for long operations

**Example:**
```python
async for chunk in client.stream_chat(messages=messages, tools=tools):
    if chunk["type"] == "content":
        print(chunk["delta"], end="")
    elif chunk["type"] == "tool_call":
        print(f"Calling: {chunk['function']['name']}")
```

### 4. **Log Probabilities** ✅
- Token-level probability information
- Top-N alternative tokens
- Useful for debugging and analysis

**Example:**
```python
result = await client.chat_with_logprobs(
    messages=messages,
    top_logprobs=5  # Get top 5 alternatives per token
)
```

### 5. **Tool Choice Control** ✅
- `"auto"` - Model decides (default)
- `"none"` - Never call tools
- `"required"` - Must call at least one tool
- `{"type": "function", "function": {"name": "X"}}` - Force specific function

**Example:**
```python
# Force model to call specific function
result = await client.force_tool_call(
    messages=messages,
    tools=tools,
    function_name="squeue"
)

# Or prevent tool calls
result = await client.chat_with_tools(
    messages=messages,
    tools=tools,
    tool_choice="none"
)
```

### 6. **Advanced Parameters** ✅
Full control over model behavior:
- `temperature` (0.0-2.0) - Randomness/creativity
- `top_p` (0.0-1.0) - Nucleus sampling
- `frequency_penalty` (-2.0 to 2.0) - Reduce repetition
- `presence_penalty` (-2.0 to 2.0) - Encourage new topics
- `max_completion_tokens` - Limit output length
- `seed` - Deterministic generation

**Example:**
```python
client = OllamaClient(
    model="qwen2.5:7b",
    temperature=0.0,      # Deterministic
    top_p=1.0,
    frequency_penalty=0.0,
    presence_penalty=0.0,
    seed=42               # Reproducible results
)
```

### 7. **Token Usage Tracking** ✅
Detailed statistics for every request:
- `prompt_tokens` - Input tokens
- `completion_tokens` - Generated tokens
- `total_tokens` - Sum

**Example:**
```python
result = await client.chat_with_tools(messages=messages, tools=tools)
print(f"Used {result['usage']['total_tokens']} tokens")
```

### 8. **Multiple Completions** ✅
Generate N different responses:
```python
response = await client.chat(messages=messages, n=3)
for i, choice in enumerate(response.choices):
    print(f"Option {i+1}: {choice.message.content}")
```

## API Endpoints

### Enhanced FastAPI Endpoints

1. **`POST /chat/structured`** - Structured Pydantic output
2. **`POST /chat/parallel`** - Parallel tool execution
3. **`POST /chat/logprobs`** - Token probabilities
4. **`GET /features`** - List all features
5. **`POST /stream`** - Streaming responses (existing)
6. **`POST /chat`** - Standard chat (existing)

## Usage Examples

### Quick Start

```python
from utils.openai_client import OllamaClient

# Initialize with custom parameters
client = OllamaClient(
    model="qwen2.5:7b",
    temperature=0.0,
    top_p=1.0
)

# Simple chat
response = await client.simple_chat([
    {"role": "user", "content": "Hello!"}
])

# With tools
result = await client.chat_with_tools(
    messages=messages,
    tools=SLURM_TOOLS,
    parallel_tool_calls=True
)
```

### Structured Output

```python
from pydantic import BaseModel

class ClusterStatus(BaseModel):
    total_nodes: int
    available_nodes: int
    running_jobs: int
    status: str

status = await client.chat_structured(
    messages=[{"role": "user", "content": "Get cluster status"}],
    response_format=ClusterStatus
)

print(f"Available: {status.available_nodes}/{status.total_nodes}")
```

### Force Specific Tool

```python
# Always call squeue, even if user asks something else
result = await client.force_tool_call(
    messages=[{"role": "user", "content": "What's the cluster?"}],
    tools=SLURM_TOOLS,
    function_name="squeue"
)
```

## Testing

Run the test suite:
```bash
# Quick tests
python test_enhanced_client.py

# Full examples
python examples_openai_features.py
```

## Configuration

### Agent Configuration

The `SlurmAgent` now supports:
```python
agent = SlurmAgent(
    model="qwen2.5:7b",
    temperature=0.0,
    max_iterations=10,
    parallel_tool_calls=True,
    logprobs=False
)
```

### Client Configuration

```python
client = OllamaClient(
    model="qwen2.5:7b",
    base_url="http://localhost:11434/v1",
    temperature=0.0,
    top_p=1.0,
    frequency_penalty=0.0,
    presence_penalty=0.0,
    max_completion_tokens=None,
    seed=None
)
```

## Performance Tips

1. **Parallel Tool Calls**: Enable for multi-command operations
2. **Temperature=0**: Use for deterministic/production outputs
3. **Streaming**: Use for long responses to show progress
4. **Structured Outputs**: Use for UI rendering or data processing
5. **Tool Choice**: Use `"required"` to ensure tool execution

## Comparison with Previous Version

| Feature | v1.0 | v2.0 (Enhanced) |
|---------|------|-----------------|
| Basic chat | ✅ | ✅ |
| Tool calling | ✅ | ✅ |
| Structured outputs | ❌ | ✅ |
| Parallel tools | ❌ | ✅ |
| Streaming | Basic | Enhanced |
| Log probabilities | ❌ | ✅ |
| Tool choice | Auto only | Auto/None/Required/Force |
| Advanced params | Temperature | All parameters |
| Usage tracking | ❌ | ✅ |

## Migration Guide

### From v1.0 to v2.0

**Old code:**
```python
client = OllamaClient(model="gpt-oss:20b")
response = await client.chat_with_tools(messages, tools)
```

**New code (backward compatible):**
```python
client = OllamaClient(
    model="qwen2.5:7b",
    temperature=0.0  # New: configurable params
)
response = await client.chat_with_tools(
    messages, 
    tools,
    parallel_tool_calls=True  # New: parallel execution
)
# New: usage tracking
print(f"Tokens used: {response['usage']['total_tokens']}")
```

## Best Practices

1. **Use Pydantic models** for structured data extraction
2. **Enable parallel_tool_calls** for independent operations
3. **Set temperature=0** for production environments
4. **Use streaming** for user-facing applications
5. **Track usage** for cost monitoring
6. **Force tool calls** when user intent is clear
7. **Use logprobs** for debugging model behavior

## Troubleshooting

### Issue: Tool not being called
**Solution**: Use `tool_choice="required"` or force specific tool

### Issue: Inconsistent outputs
**Solution**: Set `temperature=0` and `seed=42` for deterministic behavior

### Issue: Slow responses
**Solution**: Enable `parallel_tool_calls=True` and use streaming

### Issue: Invalid structured output
**Solution**: Ensure Pydantic model has all required fields

## Future Enhancements

- [ ] Image/vision input support
- [ ] Audio input/output
- [ ] Function calling with custom grammars (Lark/Regex)
- [ ] Batch API support
- [ ] Conversation state management
- [ ] Prompt caching

## References

- [OpenAI API Documentation](https://platform.openai.com/docs/)
- [Function Calling Guide](https://platform.openai.com/docs/guides/function-calling)
- [Structured Outputs Guide](https://platform.openai.com/docs/guides/structured-outputs)
- [Pydantic Documentation](https://docs.pydantic.dev/)
