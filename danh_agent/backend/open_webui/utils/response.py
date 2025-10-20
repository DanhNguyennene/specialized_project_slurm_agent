import json
from uuid import uuid4
from open_webui.utils.misc import (
    openai_chat_chunk_message_template,
    openai_chat_completion_message_template,
)


def convert_ollama_tool_call_to_openai(tool_calls: dict) -> dict:
    """
    Convert various tool call formats to OpenAI format.
    Handles LangChain ToolMessage objects, dicts, and strings.
    """
    openai_tool_calls = []
    
    for tool_call in tool_calls:
        try:
            openai_tool_call = None
            
            # Handle LangChain ToolMessage object
            if hasattr(tool_call, 'content') and hasattr(tool_call, 'name'):
                # This is a LangChain ToolMessage
                openai_tool_call = {
                    "id": getattr(tool_call, 'id', f"call_{str(uuid4())}"),
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": tool_call.content  # This contains the actual result
                    }
                }
            
            # Handle dictionary
            elif isinstance(tool_call, dict):
                openai_tool_call = tool_call
            
            # Handle JSON string
            elif isinstance(tool_call, str):
                try:
                    openai_tool_call = json.loads(tool_call)
                except json.JSONDecodeError:
                    # If not valid JSON, wrap it
                    openai_tool_call = {
                        "id": f"call_{str(uuid4())}",
                        "type": "function",
                        "function": {
                            "name": "raw_response",
                            "arguments": tool_call
                        }
                    }
            
            # Handle other objects
            else:
                # Convert object to dict representation
                obj_dict = {}
                if hasattr(tool_call, '__dict__'):
                    obj_dict = tool_call.__dict__
                else:
                    obj_dict = {"content": str(tool_call)}
                
                openai_tool_call = {
                    "id": f"call_{str(uuid4())}",
                    "type": "function",
                    "function": {
                        "name": "object_response",
                        "arguments": json.dumps(obj_dict, default=str)
                    }
                }
            
            if openai_tool_call:
                openai_tool_calls.append(openai_tool_call)
                
        except Exception as e:
            print(f"Error converting tool call: {e}")
            print(f"Tool call type: {type(tool_call)}")
            print(f"Tool call: {repr(tool_call)}")
            
            # Create error placeholder
            error_call = {
                "id": f"call_{str(uuid4())}",
                "type": "function",
                "function": {
                    "name": "conversion_error",
                    "arguments": json.dumps({
                        "error": str(e),
                        "type": str(type(tool_call)),
                        "data": str(tool_call)[:500]
                    })
                }
            }
            openai_tool_calls.append(error_call)
    print("openai_tool_calls", openai_tool_calls)
    return openai_tool_calls

def convert_ollama_usage_to_openai(data: dict) -> dict:
    return {
        "response_token/s": (
            round(
                (
                    (
                        data.get("eval_count", 0)
                        / ((data.get("eval_duration", 0) / 10_000_000))
                    )
                    * 100
                ),
                2,
            )
            if data.get("eval_duration", 0) > 0
            else "N/A"
        ),
        "prompt_token/s": (
            round(
                (
                    (
                        data.get("prompt_eval_count", 0)
                        / ((data.get("prompt_eval_duration", 0) / 10_000_000))
                    )
                    * 100
                ),
                2,
            )
            if data.get("prompt_eval_duration", 0) > 0
            else "N/A"
        ),
        "total_duration": data.get("total_duration", 0),
        "load_duration": data.get("load_duration", 0),
        "prompt_eval_count": data.get("prompt_eval_count", 0),
        "prompt_tokens": int(
            data.get("prompt_eval_count", 0)
        ),  # This is the OpenAI compatible key
        "prompt_eval_duration": data.get("prompt_eval_duration", 0),
        "eval_count": data.get("eval_count", 0),
        "completion_tokens": int(
            data.get("eval_count", 0)
        ),  # This is the OpenAI compatible key
        "eval_duration": data.get("eval_duration", 0),
        "approximate_total": (lambda s: f"{s // 3600}h{(s % 3600) // 60}m{s % 60}s")(
            (data.get("total_duration", 0) or 0) // 1_000_000_000
        ),
        "total_tokens": int(  # This is the OpenAI compatible key
            data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
        ),
        "completion_tokens_details": {  # This is the OpenAI compatible key
            "reasoning_tokens": 0,
            "accepted_prediction_tokens": 0,
            "rejected_prediction_tokens": 0,
        },
    }


def convert_response_ollama_to_openai(ollama_response: dict) -> dict:
    model = ollama_response.get("model", "ollama")
    message_content = ollama_response.get("message", {}).get("content", "")
    reasoning_content = ollama_response.get("message", {}).get("thinking", None)
    tool_calls = ollama_response.get("message", {}).get("tool_calls", None)
    openai_tool_calls = None

    if tool_calls:
        openai_tool_calls = convert_ollama_tool_call_to_openai(tool_calls)

    data = ollama_response

    usage = convert_ollama_usage_to_openai(data)

    response = openai_chat_completion_message_template(
        model, message_content, reasoning_content, openai_tool_calls, usage
    )
    return response


async def convert_streaming_response_ollama_to_openai(ollama_streaming_response):
    async for data in ollama_streaming_response.body_iterator:
        data = json.loads(data)

        model = data.get("model", "ollama")
        message_content = data.get("message", {}).get("content", None)
        reasoning_content = data.get("message", {}).get("thinking", None)
        tool_calls = data.get("message", {}).get("tool_calls", None)
        openai_tool_calls = None

        if tool_calls:
            openai_tool_calls = convert_ollama_tool_call_to_openai(tool_calls)

        done = data.get("done", False)

        usage = None
        if done:
            usage = convert_ollama_usage_to_openai(data)

        data = openai_chat_chunk_message_template(
            model, message_content, reasoning_content, openai_tool_calls, usage
        )

        line = f"data: {json.dumps(data)}\n\n"
        yield line

    yield "data: [DONE]\n\n"


def convert_embedding_response_ollama_to_openai(response) -> dict:
    """
    Convert the response from Ollama embeddings endpoint to the OpenAI-compatible format.

    Args:
        response (dict): The response from the Ollama API,
            e.g. {"embedding": [...], "model": "..."}
            or {"embeddings": [{"embedding": [...], "index": 0}, ...], "model": "..."}

    Returns:
        dict: Response adapted to OpenAI's embeddings API format.
            e.g. {
                "object": "list",
                "data": [
                    {"object": "embedding", "embedding": [...], "index": 0},
                    ...
                ],
                "model": "...",
            }
    """
    # Ollama batch-style output
    if isinstance(response, dict) and "embeddings" in response:
        openai_data = []
        for i, emb in enumerate(response["embeddings"]):
            openai_data.append(
                {
                    "object": "embedding",
                    "embedding": emb.get("embedding"),
                    "index": emb.get("index", i),
                }
            )
        return {
            "object": "list",
            "data": openai_data,
            "model": response.get("model"),
        }
    # Ollama single output
    elif isinstance(response, dict) and "embedding" in response:
        return {
            "object": "list",
            "data": [
                {
                    "object": "embedding",
                    "embedding": response["embedding"],
                    "index": 0,
                }
            ],
            "model": response.get("model"),
        }
    # Already OpenAI-compatible?
    elif (
        isinstance(response, dict)
        and "data" in response
        and isinstance(response["data"], list)
    ):
        return response

    # Fallback: return as is if unrecognized
    return response
