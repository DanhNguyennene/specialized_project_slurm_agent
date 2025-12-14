# Slurm Agent - OpenAI SDK

Clean, robust Slurm cluster management agent using OpenAI SDK with local Ollama.

## Features

- **Simple Architecture** - No complex routing or state machines
- **Comprehensive Tools** - 12 Slurm operations (sbatch, squeue, scancel, sinfo, sacct, etc.)
- **Local Execution** - Runs entirely on local Ollama
- **Structured Outputs** - Uses Pydantic for reliable response formats
- **Clean API** - FastAPI endpoints for chat, streaming, and direct tool execution

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Create `.env` file:

```bash
# Slurm Cluster
CLUSTER_IP=10.1.1.2
CLUSTER_PORT=32222
SLURM_API_KEY_1=your_api_key

# Ollama
OLLAMA_MODEL=gpt-oss:120b-cloud
OLLAMA_BASE_URL=http://localhost:11434
```

### 3. Start Server

```bash
python main_clean.py
```

Server runs on `http://localhost:20000`

## Usage

### Python Client

```python
from flow.slurm_agent import SlurmAgent

agent = SlurmAgent()

# Simple request
result = await agent.run("Show me all running jobs")
print(result["content"])

# With conversation history
messages = [
    {"role": "user", "content": "Check cluster status"},
    {"role": "assistant", "content": "The cluster has..."},
    {"role": "user", "content": "Submit a test job"}
]
result = await agent.chat(messages)
```

### API Endpoints

#### Chat
```bash
curl -X POST http://localhost:20000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "List all jobs in the queue"}
    ]
  }'
```

#### Simple Message
```bash
curl -X POST "http://localhost:20000/simple?message=Show%20cluster%20info"
```

#### Stream Response
```bash
curl -X POST http://localhost:20000/stream \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "Submit a test job"}
    ]
  }'
```

#### List Tools
```bash
curl http://localhost:20000/tools
```

#### Direct Tool Execution
```bash
curl -X POST http://localhost:20000/execute_tool \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "squeue",
    "arguments": {"state": "RUNNING"}
  }'
```

## Available Tools

| Tool | Description |
|------|-------------|
| `sbatch` | Submit batch jobs |
| `squeue` | View job queue |
| `scancel` | Cancel jobs |
| `sinfo` | Cluster information |
| `sacct` | Job accounting/history |
| `scontrol_show` | Detailed entity info |
| `srun` | Interactive execution |
| `scontrol_update` | Update properties |
| `scontrol_hold` | Hold pending jobs |
| `scontrol_release` | Release held jobs |
| `sprio` | Job priority info |
| `sshare` | Fair-share info |

## Architecture

```
┌─────────────────┐
│   FastAPI App   │  main_clean.py
└────────┬────────┘
         │
┌────────▼────────┐
│  Slurm Agent    │  flow/slurm_agent.py
└────────┬────────┘
         │
    ┌────▼─────┬────────────┐
    │          │            │
┌───▼────┐ ┌──▼───┐  ┌────▼────┐
│ OpenAI │ │Tools │  │  Slurm  │
│ Client │ │      │  │   MCP   │
└────────┘ └──────┘  └─────────┘
```

### Key Components

- **`main_clean.py`** - FastAPI server with clean endpoints
- **`flow/slurm_agent.py`** - Simple agent orchestration
- **`utils/openai_client.py`** - OpenAI SDK wrapper for Ollama
- **`utils/slurm_tools.py`** - Comprehensive Slurm tool definitions
- **`utils/slurm_tools.py:SlurmConnection`** - WebSocket MCP connection

## Example Conversations

**Check cluster status:**
```
User: "Show me the cluster status"
Agent: [Calls sinfo tool]
Agent: "The cluster has 4 nodes, 3 are idle and 1 is allocated..."
```

**Submit a job:**
```
User: "Submit a job to run 'echo hello' on 1 node"
Agent: [Calls sbatch tool with appropriate parameters]
Agent: "Job 12345 has been submitted successfully to partition 'compute'."
```

**Check job progress:**
```
User: "What's the status of job 12345?"
Agent: [Calls scontrol_show tool]
Agent: "Job 12345 is currently RUNNING on node001, started 5 minutes ago..."
```

## Configuration Options

### Agent Configuration

```python
agent = SlurmAgent(
    model="gpt-oss:120b-cloud",           # Ollama model
    base_url="http://localhost:11434/v1"  # Ollama API URL
)
```

### Connection Configuration

Set in `.env`:
- `CLUSTER_IP` - Slurm cluster IP
- `CLUSTER_PORT` - MCP server port
- `SLURM_API_KEY_1` - Authentication key

## Development

### Project Structure

```
agent/
├── main_clean.py           # FastAPI server
├── requirements.txt        # Python dependencies
├── .env                    # Configuration
├── flow/
│   └── slurm_agent.py     # Agent logic
└── utils/
    ├── openai_client.py   # OpenAI SDK wrapper
    └── slurm_tools.py     # Tool definitions
```

### Adding New Tools

1. Add function definition to `SLURM_TOOLS` in `utils/slurm_tools.py`:

```python
{
    "type": "function",
    "function": {
        "name": "my_tool",
        "description": "What it does",
        "parameters": {
            "type": "object",
            "properties": {
                "param": {"type": "string", "description": "Parameter"}
            },
            "required": ["param"]
        }
    }
}
```

2. Add to `TOOL_NAME_MAP` if MCP name differs
3. Add special handling in `execute_tool()` if needed

## Testing

```bash
# Test agent directly
python -c "
import asyncio
from flow.slurm_agent import run_agent

result = asyncio.run(run_agent('Show cluster info'))
print(result['content'])
"

# Test API
curl http://localhost:20000/health
```

## Troubleshooting

**Agent won't start:**
- Check Ollama is running: `curl http://localhost:11434`
- Verify model exists: `ollama list`

**Tool execution fails:**
- Check Slurm MCP server is running
- Verify CLUSTER_IP and CLUSTER_PORT in `.env`
- Check SLURM_API_KEY is correct

**Slow responses:**
- Larger models take longer
- Use smaller model: `OLLAMA_MODEL=llama2:7b`

## Performance

- **Response time:** 2-5 seconds typical
- **Tool execution:** ~1 second per tool
- **Max iterations:** 10 (configurable)

## Security

- API keys in environment variables
- WebSocket authentication to MCP server
- No external API calls (runs locally)

## License

[Your License]

---

**Version:** 2.0.0  
**Framework:** OpenAI SDK + Ollama  
**Python:** 3.8+
