"""
Debug response structure to find reasoning field
"""
import asyncio
from utils.openai_client import OllamaClient
from utils.slurm_commands import SlurmCommandSequence

async def main():
    client = OllamaClient(model="gpt-oss:20b")
    messages = [
        {"role": "system", "content": "Generate Slurm commands."},
        {"role": "user", "content": "Check job queue"}
    ]
    
    response = await client.chat(messages=messages, response_format=SlurmCommandSequence)
    
    print("Response object:", type(response))
    print("\nChoice:")
    choice = response.choices[0]
    print(f"  Type: {type(choice)}")
    print(f"  Attributes: {dir(choice)}")
    
    print("\nMessage:")
    message = choice.message
    print(f"  Type: {type(message)}")
    print(f"  Attributes: {[a for a in dir(message) if not a.startswith('_')]}")
    
    print(f"\n  content: '{message.content}'")
    print(f"  content type: {type(message.content)}")
    
    if hasattr(message, 'reasoning'):
        print(f"  reasoning (hasattr): '{message.reasoning}'")
    
    if hasattr(message, 'model_extra'):
        print(f"  model_extra: {message.model_extra}")
    
    if hasattr(message, '__dict__'):
        print(f"  __dict__: {message.__dict__}")
    
    if hasattr(message, 'model_dump'):
        dump = message.model_dump()
        print(f"  model_dump keys: {dump.keys()}")
        if 'reasoning' in dump:
            print(f"  model_dump['reasoning']: {dump['reasoning'][:200]}...")
    
    # Try to access as dict
    try:
        if 'reasoning' in message:
            print(f"  Dict access reasoning: {message['reasoning']}")
    except:
        pass

asyncio.run(main())
