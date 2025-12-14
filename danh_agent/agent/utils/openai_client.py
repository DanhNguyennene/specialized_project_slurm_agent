"""
Enhanced OpenAI SDK adapter with all API features:
- Structured outputs with Pydantic
- Parallel tool calling
- Streaming with delta accumulation
- Logprobs and token usage tracking
- Advanced parameters (temperature, top_p, frequency_penalty, etc.)
- Tool choice configurations
"""
from openai import AsyncOpenAI
from typing import List, Dict, Any, Optional, Type, Union, AsyncIterator, Literal
from pydantic import BaseModel
import json
import logging

logger = logging.getLogger(__name__)


class OllamaClient:
    """Enhanced OpenAI client for local Ollama with full API feature support"""
    
    def __init__(
        self, 
        model: str = "qwen2.5:7b",
        base_url: str = "http://localhost:11434/v1",
        temperature: float = 0.0,
        top_p: float = 1.0,
        frequency_penalty: float = 0.0,
        presence_penalty: float = 0.0,
        max_completion_tokens: Optional[int] = None,
        seed: Optional[int] = None
    ):
        self.model = model
        self.client = AsyncOpenAI(
            base_url=base_url,
            api_key="ollama"  # Ollama doesn't need real key
        )
        # Default parameters
        self.temperature = temperature
        self.top_p = top_p
        self.frequency_penalty = frequency_penalty
        self.presence_penalty = presence_penalty
        self.max_completion_tokens = max_completion_tokens
        self.seed = seed
    
    async def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        response_format: Optional[Union[Type[BaseModel], Dict[str, str]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = "auto",
        parallel_tool_calls: bool = True,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        frequency_penalty: Optional[float] = None,
        presence_penalty: Optional[float] = None,
        max_completion_tokens: Optional[int] = None,
        logprobs: bool = False,
        top_logprobs: Optional[int] = None,
        seed: Optional[int] = None,
        n: int = 1,
        stream: bool = False
    ):
        """
        Enhanced chat completion with all OpenAI API features
        
        Args:
            messages: List of chat messages
            tools: Optional OpenAI function definitions
            response_format: Optional Pydantic model or dict for structured output
            tool_choice: "auto", "none", "required", or {"type": "function", "function": {"name": "..."}}
            parallel_tool_calls: Whether to enable parallel function calling
            temperature: Sampling temperature (0-2)
            top_p: Nucleus sampling parameter
            frequency_penalty: Penalty for token frequency (-2.0 to 2.0)
            presence_penalty: Penalty for token presence (-2.0 to 2.0)
            max_completion_tokens: Maximum tokens to generate
            logprobs: Whether to return log probabilities
            top_logprobs: Number of most likely tokens to return (0-20)
            seed: For deterministic sampling
            n: Number of completions to generate
            stream: Whether to stream the response
        """
        params = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "top_p": top_p if top_p is not None else self.top_p,
            "frequency_penalty": frequency_penalty if frequency_penalty is not None else self.frequency_penalty,
            "presence_penalty": presence_penalty if presence_penalty is not None else self.presence_penalty,
            "n": n,
            "stream": stream,
        }
        
        # Optional parameters
        if max_completion_tokens or self.max_completion_tokens:
            params["max_tokens"] = max_completion_tokens or self.max_completion_tokens
        
        if seed or self.seed:
            params["seed"] = seed or self.seed
        
        if logprobs:
            params["logprobs"] = True
            if top_logprobs:
                params["top_logprobs"] = top_logprobs
        
        # Tool configuration
        if tools:
            params["tools"] = tools
            params["tool_choice"] = tool_choice
            params["parallel_tool_calls"] = parallel_tool_calls
        
        # Structured output configuration
        if response_format:
            if isinstance(response_format, type) and issubclass(response_format, BaseModel):
                # Pydantic model - use JSON schema with strict mode
                params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_format.__name__,
                        "schema": response_format.model_json_schema(),
                        "strict": True
                    }
                }
            else:
                # Plain dict - use as-is (e.g., {"type": "json_object"})
                params["response_format"] = response_format
        
        response = await self.client.chat.completions.create(**params)
        return response
    
    async def chat_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        tool_choice: Optional[Union[str, Dict[str, Any]]] = "auto",
        parallel_tool_calls: bool = True
    ):
        """
        Chat with tool calling support
        
        Args:
            messages: List of chat messages
            tools: List of tool definitions
            tool_choice: "auto", "none", "required", or specific function
            parallel_tool_calls: Whether to enable parallel function calling
        
        Returns:
            Dict with content, tool_calls, usage, and metadata
        """
        response = await self.chat(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls
        )
        message = response.choices[0].message
        
        return {
            "content": message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "function": {
                        "name": tc.function.name,
                        "arguments": json.loads(tc.function.arguments)
                    }
                }
                for tc in (message.tool_calls or [])
            ],
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            },
            "finish_reason": response.choices[0].finish_reason
        }
    
    async def chat_structured(
        self,
        messages: List[Dict[str, str]],
        response_format: Type[BaseModel]
    ):
        """
        Chat with structured output using Pydantic model
        
        Uses OpenAI's beta.chat.completions.parse() for proper structured outputs.
        This is the official method per Ollama documentation and works with:
        - Ollama (llama3.1, qwen2.5, etc.)
        - OpenAI/Azure API
        """
        try:
            # Use beta.parse() method - official way for structured outputs
            completion = await self.client.beta.chat.completions.parse(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                response_format=response_format,
            )
            
            message = completion.choices[0].message
            
            # Check if parsing succeeded
            if message.parsed:
                return message.parsed
            elif message.refusal:
                raise ValueError(f"Model refused: {message.refusal}")
            else:
                raise ValueError("Model returned no parsed content")
            
        except Exception as e:
            logger.error(f"Structured output failed for {self.model}: {e}")
            raise ValueError(
                f"Model {self.model} failed to generate structured output. "
                f"Error: {e}\n"
                f"Make sure you're using a model that supports structured outputs."
            )
    
    async def simple_chat(self, messages: List[Dict[str, str]]) -> str:
        """Simple chat without tools or structure"""
        response = await self.chat(messages=messages)
        return response.choices[0].message.content or ""
    
    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = "auto",
        parallel_tool_calls: bool = True
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream chat completion with delta accumulation
        
        Yields:
            Dict with type and delta/content information
        """
        params = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": True
        }
        
        if tools:
            params["tools"] = tools
            params["tool_choice"] = tool_choice
            params["parallel_tool_calls"] = parallel_tool_calls
        
        stream = await self.client.chat.completions.create(**params)
        
        async for chunk in stream:
            delta = chunk.choices[0].delta
            
            if delta.content:
                yield {
                    "type": "content",
                    "delta": delta.content
                }
            
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    yield {
                        "type": "tool_call",
                        "index": tc.index,
                        "id": tc.id,
                        "function": {
                            "name": tc.function.name if tc.function.name else None,
                            "arguments": tc.function.arguments if tc.function.arguments else ""
                        }
                    }
            
            if chunk.choices[0].finish_reason:
                yield {
                    "type": "done",
                    "finish_reason": chunk.choices[0].finish_reason
                }
    
    async def chat_with_logprobs(
        self,
        messages: List[Dict[str, str]],
        top_logprobs: int = 5
    ):
        """
        Chat with log probability information
        
        Args:
            messages: List of chat messages
            top_logprobs: Number of top tokens to return (1-20)
        
        Returns:
            Dict with content, logprobs, and usage
        """
        response = await self.chat(
            messages=messages,
            logprobs=True,
            top_logprobs=top_logprobs
        )
        
        message = response.choices[0].message
        logprobs_data = response.choices[0].logprobs
        
        return {
            "content": message.content,
            "logprobs": {
                "content": [
                    {
                        "token": token.token,
                        "logprob": token.logprob,
                        "top_logprobs": [
                            {
                                "token": top.token,
                                "logprob": top.logprob
                            }
                            for top in token.top_logprobs
                        ] if token.top_logprobs else []
                    }
                    for token in logprobs_data.content
                ] if logprobs_data and logprobs_data.content else []
            },
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            }
        }
    
    async def force_tool_call(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        function_name: str
    ):
        """
        Force the model to call a specific function
        
        Args:
            messages: List of chat messages
            tools: List of tool definitions
            function_name: Name of the function to force
        
        Returns:
            Dict with tool call information
        """
        response = await self.chat(
            messages=messages,
            tools=tools,
            tool_choice={
                "type": "function",
                "function": {"name": function_name}
            }
        )
        
        message = response.choices[0].message
        
        if message.tool_calls:
            tc = message.tool_calls[0]
            return {
                "id": tc.id,
                "function": {
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments)
                }
            }
        return None

