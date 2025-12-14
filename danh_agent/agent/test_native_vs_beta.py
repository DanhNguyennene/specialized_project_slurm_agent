"""
Test Ollama's native format parameter vs OpenAI beta.parse()
"""
from openai import AsyncOpenAI
from pydantic import BaseModel
import asyncio
import json


class SimpleResponse(BaseModel):
    answer: str
    confidence: float


async def test_native_format(model: str):
    """Test using Ollama's native 'format' parameter"""
    print(f"\n{'='*60}")
    print(f"Testing NATIVE format: {model}")
    print('='*60)
    
    client = AsyncOpenAI(
        base_url="http://localhost:11434/v1",
        api_key="ollama"
    )
    
    try:
        # Use Ollama's native JSON schema format
        completion = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": "What is 2+2? Respond with high confidence."}
            ],
            format=SimpleResponse.model_json_schema(),  # Ollama native way
            temperature=0
        )
        
        message = completion.choices[0].message
        print(f"\n✅ Response received")
        print(f"Content: {message.content}")
        
        # Parse manually
        parsed = SimpleResponse.model_validate_json(message.content)
        print(f"Parsed: {parsed}")
        print(f"Answer: {parsed.answer}")
        print(f"Confidence: {parsed.confidence}")
        
    except Exception as e:
        print(f"\n❌ Failed: {e}")
        import traceback
        traceback.print_exc()


async def test_beta_parse(model: str):
    """Test using OpenAI compatible beta.parse()"""
    print(f"\n{'='*60}")
    print(f"Testing BETA.PARSE: {model}")
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
        
        message = completion.choices[0].message
        print(f"\n✅ Response received")
        print(f"Content: {message.content}")
        print(f"Parsed: {message.parsed}")
        
        if message.parsed:
            print(f"Answer: {message.parsed.answer}")
            print(f"Confidence: {message.parsed.confidence}")
        
    except Exception as e:
        print(f"\n❌ Failed: {e}")


async def main():
    print("Comparing Ollama native format vs OpenAI beta.parse()")
    
    model = "gpt-oss:20b"
    
    await test_native_format(model)
    await test_beta_parse(model)
    
    print(f"\n{'='*60}")
    print("COMPLETE")
    print('='*60)


if __name__ == "__main__":
    asyncio.run(main())
