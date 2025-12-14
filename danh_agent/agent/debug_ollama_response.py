"""
Debug what Ollama is actually returning
"""
import asyncio
import json
from utils.openai_client import OllamaClient
from utils.slurm_commands import SlurmCommandSequence

async def debug_response():
    print("\n" + "="*70)
    print("DEBUG: What is Ollama returning?")
    print("="*70)
    
    client = OllamaClient(model="gpt-oss:20b")
    
    messages = [
        {"role": "system", "content": "Generate a Slurm command to check the job queue."},
        {"role": "user", "content": "Check job queue"}
    ]
    
    print("\n[1] Testing with response_format=SlurmCommandSequence...")
    try:
        response = await client.chat(
            messages=messages,
            response_format=SlurmCommandSequence
        )
        
        print(f"Response type: {type(response)}")
        print(f"Response: {response}")
        
        if hasattr(response, 'choices') and response.choices:
            choice = response.choices[0]
            print(f"\nChoice type: {type(choice)}")
            print(f"Message: {choice.message}")
            print(f"Content: {choice.message.content}")
            print(f"Content type: {type(choice.message.content)}")
            print(f"Content length: {len(choice.message.content) if choice.message.content else 0}")
            
            if choice.message.content:
                print(f"\nRaw content:\n{repr(choice.message.content)}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "="*70)
    print("[2] Testing without response_format (normal chat)...")
    try:
        response = await client.chat(messages=messages)
        
        content = response.choices[0].message.content
        print(f"Content: {content}")
        print(f"Content type: {type(content)}")
        
    except Exception as e:
        print(f"Error: {e}")
    
    print("\n" + "="*70)
    print("[3] Testing with qwen2.5:7b...")
    try:
        client7b = OllamaClient(model="qwen2.5:7b")
        response = await client7b.chat(
            messages=messages,
            response_format=SlurmCommandSequence
        )
        
        content = response.choices[0].message.content
        print(f"Content length: {len(content) if content else 0}")
        print(f"Content preview: {content[:200] if content else 'EMPTY'}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(debug_response())
