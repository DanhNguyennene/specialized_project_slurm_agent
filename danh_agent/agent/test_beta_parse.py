"""
Test beta.parse() directly with both models
"""
from openai import AsyncOpenAI
from pydantic import BaseModel
import asyncio


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
        
        message = completion.choices[0].message
        print(f"\n✅ Success!")
        print(f"Parsed object: {message.parsed}")
        print(f"Type: {type(message.parsed)}")
        print(f"Answer: {message.parsed.answer}")
        print(f"Confidence: {message.parsed.confidence}")
        
        if message.refusal:
            print(f"⚠️  Refusal: {message.refusal}")
            
    except Exception as e:
        print(f"\n❌ Failed: {e}")
        print(f"Error type: {type(e).__name__}")


async def main():
    print("Testing beta.chat.completions.parse() with Ollama models")
    
    # Test both models
    await test_model("qwen2.5:7b")
    await test_model("gpt-oss:20b")
    
    print(f"\n{'='*60}")
    print("COMPLETE")
    print('='*60)


if __name__ == "__main__":
    asyncio.run(main())
