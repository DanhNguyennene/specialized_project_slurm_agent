"""
Inspect the raw response from beta.parse()
"""
from openai import AsyncOpenAI
from pydantic import BaseModel
import asyncio
import json


class SimpleResponse(BaseModel):
    answer: str
    confidence: float


async def test_model(model: str):
    print(f"\n{'='*60}")
    print(f"Testing: {model}")
    print('='*60)
    
    client = AsyncOpenAI(
        base_url="http://localhost:11434/v1",
        api_key="ollama"
    )
    
    try:
        completion = await client.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "user", "content": "What is 2+2? Respond with high confidence."}
            ],
            response_format=SimpleResponse,
            temperature=0
        )
        
        print(f"\n📦 Raw completion object:")
        print(f"Type: {type(completion)}")
        print(f"Model: {completion.model}")
        print(f"ID: {completion.id}")
        
        choice = completion.choices[0]
        print(f"\n📦 Choice 0:")
        print(f"Finish reason: {choice.finish_reason}")
        
        message = choice.message
        print(f"\n📦 Message:")
        print(f"Role: {message.role}")
        print(f"Content: {message.content}")
        print(f"Parsed: {message.parsed}")
        print(f"Refusal: {message.refusal}")
        
        # Check for extra fields
        if hasattr(message, 'model_extra'):
            print(f"Model extra: {message.model_extra}")
        if hasattr(message, '__dict__'):
            print(f"\nAll message attributes:")
            for key, value in message.__dict__.items():
                print(f"  {key}: {value}")
        
    except Exception as e:
        print(f"\n❌ Failed: {e}")
        import traceback
        traceback.print_exc()


async def main():
    print("Inspecting beta.chat.completions.parse() responses")
    
    # Test both models
    await test_model("qwen2.5:7b")
    await test_model("gpt-oss:20b")
    
    print(f"\n{'='*60}")
    print("COMPLETE")
    print('='*60)


if __name__ == "__main__":
    asyncio.run(main())
