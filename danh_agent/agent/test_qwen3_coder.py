"""
Test qwen3-coder:latest with structured outputs
"""
from openai import AsyncOpenAI
from pydantic import BaseModel
import asyncio
import time


class SimpleResponse(BaseModel):
    answer: str
    confidence: float


async def test_simple():
    """Test with simple response"""
    print(f"\n{'='*60}")
    print(f"TEST 1: Simple structured output")
    print('='*60)
    
    client = AsyncOpenAI(
        base_url="http://localhost:11434/v1",
        api_key="ollama"
    )
    
    start = time.time()
    try:
        completion = await client.beta.chat.completions.parse(
            model="qwen3-coder:latest",
            messages=[
                {"role": "user", "content": "What is 2+2? Respond with high confidence."}
            ],
            response_format=SimpleResponse,
            temperature=0
        )
        
        elapsed = time.time() - start
        message = completion.choices[0].message
        
        print(f"\n✅ Success in {elapsed:.1f}s")
        print(f"Content: {message.content}")
        print(f"Parsed: {message.parsed}")
        
        if message.parsed:
            print(f"Answer: {message.parsed.answer}")
            print(f"Confidence: {message.parsed.confidence}")
        
    except Exception as e:
        elapsed = time.time() - start
        print(f"\n❌ Failed in {elapsed:.1f}s: {e}")


async def test_slurm_commands():
    """Test with actual Slurm command generation"""
    print(f"\n{'='*60}")
    print(f"TEST 2: Slurm command sequence generation")
    print('='*60)
    
    # Import Slurm models
    import sys
    sys.path.insert(0, '/mnt/e/workspace/uni/specialized_project/danh_agent/agent')
    from utils.slurm_commands import SlurmCommandSequence
    
    client = AsyncOpenAI(
        base_url="http://localhost:11434/v1",
        api_key="ollama"
    )
    
    SYSTEM_PROMPT = """You are an expert Slurm workload manager assistant that generates command sequences.

Available command types (use exact type names):
- sbatch: Submit batch jobs
- squeue: Check job queue
- scancel: Cancel jobs
- sinfo: View cluster info
- sacct: Job accounting
- scontrol_show: Show detailed info
- srun: Run interactive jobs
- scontrol_update: Update jobs
- scontrol_hold: Hold jobs
- scontrol_release: Release jobs
- sprio: Job priority
- sshare: Fair share info

Generate a sequence of commands to accomplish the user's task."""

    requests = [
        "Check the job queue",
        "Show cluster information",
        "Submit a training job with 4 GPUs and 32GB RAM"
    ]
    
    for i, request in enumerate(requests, 1):
        print(f"\n--- Request {i}/{len(requests)}: {request}")
        
        start = time.time()
        try:
            completion = await client.beta.chat.completions.parse(
                model="qwen3-coder:latest",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": request}
                ],
                response_format=SlurmCommandSequence,
                temperature=0
            )
            
            elapsed = time.time() - start
            message = completion.choices[0].message
            
            if message.parsed:
                seq = message.parsed
                print(f"✅ Success in {elapsed:.1f}s")
                print(f"Description: {seq.description}")
                print(f"Commands: {len(seq.commands)}")
                for j, cmd in enumerate(seq.commands, 1):
                    print(f"  {j}. {cmd.__class__.__name__}")
            else:
                print(f"❌ Failed in {elapsed:.1f}s: No parsed content")
                print(f"Content: {message.content}")
            
        except Exception as e:
            elapsed = time.time() - start
            print(f"❌ Failed in {elapsed:.1f}s: {e}")


async def main():
    print("Testing qwen3-coder:latest with structured outputs")
    
    await test_simple()
    await test_slurm_commands()
    
    print(f"\n{'='*60}")
    print("COMPLETE")
    print('='*60)


if __name__ == "__main__":
    asyncio.run(main())
