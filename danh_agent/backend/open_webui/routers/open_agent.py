import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Literal, Optional, overload, Union

import aiohttp
from aiocache import cached
import requests
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, validator
from starlette.background import BackgroundTask

from open_webui.models.models import Models
from open_webui.config import (
    CACHE_DIR,
)
from open_webui.env import (
    MODELS_CACHE_TTL,
    AIOHTTP_CLIENT_SESSION_SSL,
    AIOHTTP_CLIENT_TIMEOUT,
    AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST,
    ENABLE_FORWARD_USER_INFO_HEADERS,
    BYPASS_MODEL_ACCESS_CONTROL,
)
from open_webui.models.users import UserModel

from open_webui.constants import ERROR_MESSAGES
from open_webui.env import ENV, SRC_LOG_LEVELS


from open_webui.utils.payload import (
    apply_model_params_to_body_ollama,
    apply_model_system_prompt_to_body,
)

from open_webui.utils.misc import (
    convert_logit_bias_input_to_json,
)

from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.access_control import has_access


log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["OPENAI"])


##########################################
#
# Utility functions
#
##########################################


async def send_get_request(url, key=None, user: UserModel = None):
    log.info(f"send_get_request() url: {url}, key: {key}, user: {user}")
    
    timeout = aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST)
    try:
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.get(
                url,
                headers={
                    **({"Authorization": f"Bearer {key}"} if key else {}),
                    **(
                        {
                            "X-OpenWebUI-User-Name": quote(user.name, safe=" "),
                            "X-OpenWebUI-User-Id": user.id,
                            "X-OpenWebUI-User-Email": user.email,
                            "X-OpenWebUI-User-Role": user.role,
                        }
                        if ENABLE_FORWARD_USER_INFO_HEADERS and user
                        else {}
                    ),
                },
                ssl=AIOHTTP_CLIENT_SESSION_SSL,
            ) as response:
                return await response.json()
    except Exception as e:
        # Handle connection error here
        log.error(f"Connection error: {e}")
        return None


async def cleanup_response(
    response: Optional[aiohttp.ClientResponse],
    session: Optional[aiohttp.ClientSession],
):
    if response:
        response.close()
    if session:
        await session.close()


##########################################
#
# API routes
#
##########################################

router = APIRouter()

# async def get_all_models_responses(request: Request, user: UserModel) -> list:
#     log.info("get_all_models_responses()")

#     # # Check if API KEYS length is same than API URLS length
#     # num_urls = len(request.app.state.config.OPENAI_API_BASE_URLS)
#     # num_keys = len(request.app.state.config.OPENAI_API_KEYS)

#     # if num_keys != num_urls:
#     #     # if there are more keys than urls, remove the extra keys
#     #     if num_keys > num_urls:
#     #         new_keys = request.app.state.config.OPENAI_API_KEYS[:num_urls]
#     #         request.app.state.config.OPENAI_API_KEYS = new_keys
#     #     # if there are more urls than keys, add empty keys
#     #     else:
#     #         request.app.state.config.OPENAI_API_KEYS += [""] * (num_urls - num_keys)

#     request_tasks = []
#     for idx, url in enumerate(request.app.state.config.OPENAI_API_BASE_URLS):
#         if (str(idx) not in request.app.state.config.OPENAI_API_CONFIGS) and (
#             url not in request.app.state.config.OPENAI_API_CONFIGS  # Legacy support
#         ):
#             request_tasks.append(
#                 send_get_request(
#                     f"{url}/models",
#                     request.app.state.config.OPENAI_API_KEYS[idx],
#                     user=user,
#                 )
#             )
#         else:
#             api_config = request.app.state.config.OPENAI_API_CONFIGS.get(
#                 str(idx),
#                 request.app.state.config.OPENAI_API_CONFIGS.get(
#                     url, {}
#                 ),  # Legacy support
#             )

#             enable = api_config.get("enable", True)
#             model_ids = api_config.get("model_ids", [])

#             if enable:
#                 if len(model_ids) == 0:
#                     request_tasks.append(
#                         send_get_request(
#                             f"{url}/models",
#                             request.app.state.config.OPENAI_API_KEYS[idx],
#                             user=user,
#                         )
#                     )
#                 else:
#                     model_list = {
#                         "object": "list",
#                         "data": [
#                             {
#                                 "id": model_id,
#                                 "name": model_id,
#                                 "owned_by": "openai",
#                                 "openai": {"id": model_id},
#                                 "urlIdx": idx,
#                             }
#                             for model_id in model_ids
#                         ],
#                     }

#                     request_tasks.append(
#                         asyncio.ensure_future(asyncio.sleep(0, model_list))
#                     )
#             else:
#                 request_tasks.append(asyncio.ensure_future(asyncio.sleep(0, None)))

#     responses = await asyncio.gather(*request_tasks)

#     for idx, response in enumerate(responses):
#         if response:
#             url = request.app.state.config.OPENAI_API_BASE_URLS[idx]
#             api_config = request.app.state.config.OPENAI_API_CONFIGS.get(
#                 str(idx),
#                 request.app.state.config.OPENAI_API_CONFIGS.get(
#                     url, {}
#                 ),  # Legacy support
#             )

#             connection_type = api_config.get("connection_type", "external")
#             prefix_id = api_config.get("prefix_id", None)
#             tags = api_config.get("tags", [])

#             for model in (
#                 response if isinstance(response, list) else response.get("data", [])
#             ):
#                 if prefix_id:
#                     model["id"] = f"{prefix_id}.{model['id']}"

#                 if tags:
#                     model["tags"] = tags

#                 if connection_type:
#                     model["connection_type"] = connection_type

#     log.debug(f"get_all_models:responses() {responses}")
#     return responses


# async def get_filtered_models(models, user):
#     # Filter models based on user access control
#     filtered_models = []
#     for model in models.get("data", []):
#         model_info = Models.get_model_by_id(model["id"])
#         if model_info:
#             if user.id == model_info.user_id or has_access(
#                 user.id, type="read", access_control=model_info.access_control
#             ):
#                 filtered_models.append(model)
#     return filtered_models


@cached(ttl=MODELS_CACHE_TTL)
async def get_all_models(request: Request, user: UserModel) -> dict[str, list]:
    log.info("get_all_models()")
    # return {"data": ["agent_007"]}
    return {"data": 
            [{
            'id': 'BK_Slurm Agent', 'object': 'model', 'created': 7, 
            'owned_by': 'tma', 'connection_type': 'external', 'name': 'Slurm Agent', 
            'BK_Slurm Agent': {'id': 'BK_Slurm Agent', 'object': 'model', 'created': 7, 'owned_by': 'tma', 'connection_type': 'external'}, 
            'urlIdx': 0
            }]
            }


@router.get("/models")
@router.get("/models/{url_idx}")
async def get_models(
    request: Request, url_idx: Optional[int] = None, user=Depends(get_verified_user)
):
    models = {
        "data": [],
    }

    if url_idx is None:
        models = await get_all_models(request, user=user)
    else:
        url = request.app.state.config.OPENAI_API_BASE_URLS[url_idx]
        key = request.app.state.config.OPENAI_API_KEYS[url_idx]

        api_config = request.app.state.config.OPENAI_API_CONFIGS.get(
            str(url_idx),
            request.app.state.config.OPENAI_API_CONFIGS.get(url, {}),  # Legacy support
        )

        r = None
        async with aiohttp.ClientSession(
            trust_env=True,
            timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST),
        ) as session:
            try:
                headers = {
                    "Content-Type": "application/json",
                    **(
                        {
                            "X-OpenWebUI-User-Name": quote(user.name, safe=" "),
                            "X-OpenWebUI-User-Id": user.id,
                            "X-OpenWebUI-User-Email": user.email,
                            "X-OpenWebUI-User-Role": user.role,
                        }
                        if ENABLE_FORWARD_USER_INFO_HEADERS
                        else {}
                    ),
                }

                if api_config.get("azure", False):
                    models = {
                        "data": api_config.get("model_ids", []) or [],
                        "object": "list",
                    }
                else:
                    headers["Authorization"] = f"Bearer {key}"

                    async with session.get(
                        f"{url}/models",
                        headers=headers,
                        ssl=AIOHTTP_CLIENT_SESSION_SSL,
                    ) as r:
                        if r.status != 200:
                            # Extract response error details if available
                            error_detail = f"HTTP Error: {r.status}"
                            res = await r.json()
                            if "error" in res:
                                error_detail = f"External Error: {res['error']}"
                            raise Exception(error_detail)

                        response_data = await r.json()

                        # Check if we're calling OpenAI API based on the URL
                        if "api.openai.com" in url:
                            # Filter models according to the specified conditions
                            response_data["data"] = [
                                model
                                for model in response_data.get("data", [])
                                if not any(
                                    name in model["id"]
                                    for name in [
                                        "babbage",
                                        "dall-e",
                                        "davinci",
                                        "embedding",
                                        "tts",
                                        "whisper",
                                    ]
                                )
                            ]

                        models = response_data
            except aiohttp.ClientError as e:
                # ClientError covers all aiohttp requests issues
                log.exception(f"Client error: {str(e)}")
                raise HTTPException(
                    status_code=500, detail="Open WebUI: Server Connection Error"
                )
            except Exception as e:
                log.exception(f"Unexpected error: {e}")
                error_detail = f"Unexpected error: {str(e)}"
                raise HTTPException(status_code=500, detail=error_detail)

    if user.role == "user" and not BYPASS_MODEL_ACCESS_CONTROL:
        models["data"] = await get_filtered_models(models, user)

    return models


class ConnectionVerificationForm(BaseModel):
    url: str
    key: str

    config: Optional[dict] = None


@router.post("/verify")
async def verify_connection(
    form_data: ConnectionVerificationForm, user=Depends(get_admin_user)
):
    url = form_data.url
    key = form_data.key

    api_config = form_data.config or {}

    async with aiohttp.ClientSession(
        trust_env=True,
        timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST),
    ) as session:
        try:
            return {
                "object": "list",
                "data": [
                    {
                        "id": "007",
                        "object": "model",
                        "created": 0000000000,
                        "owned_by": "BK"
                    }
                ]
            }

        except aiohttp.ClientError as e:
            # ClientError covers all aiohttp requests issues
            log.exception(f"Client error: {str(e)}")
            raise HTTPException(
                status_code=500, detail="Open WebUI: Server Connection Error"
            )
        except Exception as e:
            log.exception(f"Unexpected error: {e}")
            error_detail = f"Unexpected error: {str(e)}"
            raise HTTPException(status_code=500, detail=error_detail)

class ChatMessage(BaseModel):
    role: str
    content: Optional[str] = None
    tool_calls: Optional[list[dict]] = None
    images: Optional[list[str]] = None
    task: Optional[str] = "chat"  # Default to "chat"
    
    model_config = ConfigDict(extra="allow")  # Allow extra fields from OpenWebUI
    
class GenerateChatCompletionForm(BaseModel):
    model: str
    messages: list[ChatMessage]
    format: Optional[Union[dict, str]] = None
    options: Optional[dict] = None
    template: Optional[str] = None
    stream: Optional[bool] = True
    keep_alive: Optional[Union[int, str]] = None
    tools: Optional[list[dict]] = None
    model_config = ConfigDict(
        extra="allow",
    )

@router.post("/chat/completions")
async def generate_chat_completion(
    request: Request,
    form_data: dict,
    url_idx: Optional[int] = None,
    user=Depends(get_verified_user),
    bypass_filter: Optional[bool] = False,
):
    if BYPASS_MODEL_ACCESS_CONTROL:
        bypass_filter = True

    metadata = form_data.pop("metadata", None)
    try:
        form_data = GenerateChatCompletionForm(**form_data)
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )

    if isinstance(form_data, BaseModel):
        payload = {**form_data.model_dump(exclude_none=True)}

    if "metadata" in payload:
        del payload["metadata"]

    model_id = payload["model"]
    
    # BK_Slurm Agent is a virtual model - bypass database lookup
    if model_id == "BK_Slurm Agent":
        bypass_filter = True
    
    model_info = Models.get_model_by_id(model_id)

    if model_info:
        if model_info.base_model_id:
            payload["model"] = model_info.base_model_id

        params = model_info.params.model_dump()

        if params:
            system = params.pop("system", None)

            payload = apply_model_params_to_body_ollama(params, payload)
            payload = apply_model_system_prompt_to_body(system, payload, metadata, user)

        # Check if user has access to the model
        if not bypass_filter and user.role == "user":
            if not (
                user.id == model_info.user_id
                or has_access(
                    user.id, type="read", access_control=model_info.access_control
                )
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Model not found",
                )
    elif not bypass_filter:
        if user.role != "admin":
            raise HTTPException(
                status_code=403,
                detail="Model not found",
            )
    payload["model"] = "BK_Slurm Agent"
    # return {
    #     'model': 'BK_Slurm Agent',
    #     'created_at': '2025-07-24T14:55:04.611116099Z',
    #     'message': {'role': 'assistant', 'content': 'Hi'},
    #     'done_reason': 'load',
    #     'done': True
    # }
    task = metadata.get("task", "chat")
    
    # Forward chat_id to agent for session management
    chat_id = metadata.get("chat_id") if metadata else None
    if chat_id:
        payload["chat_id"] = chat_id
    
    # Also forward user_id for fallback session tracking
    if user and user.id:
        payload["user_id"] = user.id
    
    for message in payload.get("messages"):
        message["task"] = task
    print(f"Payload: {payload}")
    res =  await send_post_request(
        url="/v1/chat/completions",  # Use the streaming endpoint
        payload=json.dumps(payload),
        stream=form_data.stream,
        content_type="application/json",  # Standard JSON content type
        user=user,
    )
    print(f"Response: {res}")
    return res
async def send_post_request(
    url: str,
    payload: str,
    stream: bool = False,
    content_type: str = "application/json",
    user=None,
):
    """
    Fixed version that properly handles streaming responses
    """
    
    async def stream_response():
        try:
            print(f"DEBUG: Sending streaming request to {url}")
            print(f"DEBUG: Payload: {payload[:200]}...")
            
            import aiohttp
            time = __import__("time")
            # Your FastAPI agent service URL
            AGENT_SERVICE_URL = "http://10.0.0.1:20000"  # Replace with your actual URL
            full_url = f"{AGENT_SERVICE_URL}{url}"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    full_url,
                    data=payload,
                    headers={
                        "Content-Type": content_type,
                        "Accept": "text/event-stream" if stream else "application/json"
                    }
                ) as response:
                    
                    print(f"DEBUG: Agent service responded with status {response.status}")
                    
                    if response.status != 200:
                        error_data = await response.text()
                        print(f"DEBUG: Error from agent service: {error_data}")
                        
                        # Send error as SSE chunk
                        error_chunk = {
                            "id": "error",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": "BK_agent_007",
                            "choices": [{
                                "index": 0,
                                "delta": {
                                    "role": "assistant",
                                    "content": f"Agent service error ({response.status}): {error_data}"
                                },
                                "finish_reason": "stop"
                            }]
                        }
                        yield f"data: {json.dumps(error_chunk)}\n\n"
                        return
                    
                    if stream:
                        # Handle streaming response
                        print("DEBUG: Processing streaming response")
                        buffer = ""
                        
                        async for chunk in response.content.iter_chunked(1024):
                            chunk_text = chunk.decode('utf-8', errors='ignore')
                            buffer += chunk_text
                            
                            # Process complete SSE events (split by double newline)
                            while '\n\n' in buffer:
                                event, buffer = buffer.split('\n\n', 1)
                                event = event.strip()
                                if event:
                                    print(f"DEBUG: SSE event: {event[:100]}...")
                                    
                                    # Forward the event as-is if it's already SSE format
                                    if event.startswith('data: '):
                                        yield f"{event}\n\n"
                                    else:
                                        # Wrap in SSE format
                                        yield f"data: {event}\n\n"
                        
                        # Process any remaining buffer
                        if buffer.strip():
                            event = buffer.strip()
                            print(f"DEBUG: Final buffer: {event}")
                            if event.startswith('data: '):
                                yield f"{event}\n\n"
                            else:
                                yield f"data: {event}\n\n"
                        
                        # Send [DONE] signal to end the stream (required by OpenWebUI)
                        yield "data: [DONE]\n\n"
                        print("DEBUG: Stream complete, sent [DONE]")
                    else:
                        # Non-streaming response
                        data = await response.json()
                        print(f"DEBUG: Non-streaming response: {data}")
                        yield json.dumps(data)
                        
        except Exception as e:
            print(f"DEBUG: Exception in send_post_request: {e}")
            error_chunk = {
                "id": "error", 
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "BK_agent_007",
                "choices": [{
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "content": f"Request failed: {str(e)}"
                    },
                    "finish_reason": "stop"
                }]
            }
            yield f"data: {json.dumps(error_chunk)}\n\n"
    
    if stream:
        return StreamingResponse(
            stream_response(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )
    else:
        # Non-streaming case
        async for response in stream_response():
            return json.loads(response)
