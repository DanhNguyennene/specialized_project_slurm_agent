"""
OpenAI SDK adapter for local Ollama server
Allows using OpenAI SDK with Ollama for local LLM execution
"""
import os
from openai import AsyncOpenAI
from typing import List, Dict, Any, Optional, AsyncGenerator
import json

class OllamaOpenAIAdapter:
    """Adapter to use OpenAI SDK with local Ollama server"""
    
    def __init__(
        self, 
        model: str = "gpt-oss:120b-cloud",
        base_url: str = "http://localhost:11434/v1",
        temperature: float = 0.0,
        api_key: str = "ollama"  # Ollama doesn't need a real key
    ):
        self.model = model
        self.base_url = base_url
        self.temperature = temperature
        
        # Initialize OpenAI client pointing to Ollama
        self.client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key
        )
    
    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
        **kwargs
    ) -> Any:
        """
        Create a chat completion using OpenAI SDK format
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            tools: Optional list of function definitions in OpenAI format
            stream: Whether to stream the response
            **kwargs: Additional arguments for the API call
        
        Returns:
            Chat completion response
        """
        params = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "stream": stream,
        }
        
        # Add tools if provided
        if tools:
            params["tools"] = tools
            params["tool_choice"] = kwargs.get("tool_choice", "auto")
        
        # Add any additional parameters
        for key in ["max_tokens", "top_p", "frequency_penalty", "presence_penalty"]:
            if key in kwargs:
                params[key] = kwargs[key]
        
        if stream:
            return await self.client.chat.completions.create(**params)
        else:
            response = await self.client.chat.completions.create(**params)
            return response
    
    async def stream_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> AsyncGenerator:
        """
        Stream chat completion responses
        
        Args:
            messages: List of message dicts
            tools: Optional function definitions
            **kwargs: Additional parameters
            
        Yields:
            Streaming response chunks
        """
        stream = await self.chat_completion(
            messages=messages,
            tools=tools,
            stream=True,
            **kwargs
        )
        
        async for chunk in stream:
            yield chunk
    
    def format_message(self, role: str, content: str) -> Dict[str, str]:
        """Format a message in OpenAI format"""
        return {
            "role": role,
            "content": content
        }
    
    def format_tool_call_message(
        self, 
        tool_calls: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Format an assistant message with tool calls"""
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": tool_calls
        }
    
    def format_tool_response(
        self,
        tool_call_id: str,
        name: str,
        content: str
    ) -> Dict[str, Any]:
        """Format a tool response message"""
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": name,
            "content": content
        }
    
    @staticmethod
    def convert_function_to_tool(
        name: str,
        description: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Convert a function definition to OpenAI tool format
        
        Args:
            name: Function name
            description: Function description
            parameters: JSON schema for parameters
            
        Returns:
            Tool definition in OpenAI format
        """
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters
            }
        }
    
    @staticmethod
    def extract_tool_calls(response) -> List[Dict[str, Any]]:
        """Extract tool calls from OpenAI response"""
        if not response.choices:
            return []
        
        message = response.choices[0].message
        if not hasattr(message, 'tool_calls') or not message.tool_calls:
            return []
        
        tool_calls = []
        for tool_call in message.tool_calls:
            tool_calls.append({
                "id": tool_call.id,
                "type": tool_call.type,
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments
                }
            })
        
        return tool_calls
    
    @staticmethod
    def extract_content(response) -> str:
        """Extract content from OpenAI response"""
        if not response.choices:
            return ""
        
        message = response.choices[0].message
        return message.content or ""
    
    async def invoke(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Invoke the model and return a structured response
        
        Returns:
            Dict with 'content', 'tool_calls', and 'raw_response'
        """
        response = await self.chat_completion(
            messages=messages,
            tools=tools,
            stream=False,
            **kwargs
        )
        
        return {
            "content": self.extract_content(response),
            "tool_calls": self.extract_tool_calls(response),
            "raw_response": response
        }


# Factory function for easy initialization
def create_ollama_client(
    model: str = "gpt-oss:120b-cloud",
    base_url: str = "http://localhost:11434/v1",
    temperature: float = 0.0
) -> OllamaOpenAIAdapter:
    """
    Create an Ollama client using OpenAI SDK
    
    Args:
        model: Model name in Ollama
        base_url: Ollama server URL with /v1 suffix
        temperature: Temperature for generation
        
    Returns:
        OllamaOpenAIAdapter instance
    """
    return OllamaOpenAIAdapter(
        model=model,
        base_url=base_url,
        temperature=temperature
    )
