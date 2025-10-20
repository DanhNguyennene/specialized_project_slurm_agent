from typing import Literal
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode
from langchain.schema.runnable.config import RunnableConfig
from langchain_core.messages import HumanMessage
from langchain_ollama import OllamaLLM

import chainlit as cl
model = OllamaLLM(base_url="http://localhost:11434", model = "llama3.2:7b", streaming=True)
final_model = OllamaLLM(base_url="http://localhost:11434", model = "llama3.2:7b", streaming=True)



#model = ChatOpenAI(model_name="gpt-3.5-turbo", temperature=0)
#final_model = ChatOpenAI(model_name="gpt-3.5-turbo", temperature=0)

# NOTE: this is where we're adding a tag that we'll can use later to filter the model stream events to only the model called in the final node.
# This is not necessary if you call a single LLM but might be important in case you call multiple models within the node and want to filter events
# from only one of them.
final_model = final_model.with_config(tags=["final_node"])

from typing import Annotated
from typing_extensions import TypedDict

from langgraph.graph import END, StateGraph, START
from langgraph.graph.message import MessagesState
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage



def call_model(state: MessagesState):
    print("\n*********************Model**************************\n")
    messages = state["messages"]
    response = model.invoke(messages)
    return {"messages": [response]}


def call_final_model(state: MessagesState):
    print("\n*********************FinalModel**************************\n")
    messages = state["messages"]
    last_ai_message = messages[-1]
    response = final_model.invoke(
        [
            SystemMessage("Rewrite this in the voice of Chat GPT, act exactly like Chat GPT"),
            HumanMessage(last_ai_message.content),
        ]
    )
    return {"messages": [response]}


builder = StateGraph(MessagesState)

builder.add_node("agent", call_model)
builder.add_node("final", call_final_model)

builder.add_edge(START, "agent")
builder.add_edge("agent", "final")
builder.add_edge("final", END)

graph = builder.compile()

@cl.on_message
async def on_message(msg: cl.Message):
    config = {"configurable": {"thread_id": cl.context.session.id}}
    cb = cl.LangchainCallbackHandler()
    final_answer = cl.Message(content="answer")
    
    print(msg.content)

    for msg in graph.stream({"messages": [HumanMessage(content=msg.content)]}, stream_mode="values", config=RunnableConfig(callbacks=[cb], **config)):
        print(f"OUTPUT:\n{msg} ENDOF ReviewAgent\n")
        
    print(f"FINAL ANSWER1: {msg}")

    # for msg, metadata in graph.stream({"messages": [HumanMessage(content=msg.content)]}, stream_mode="messages", config=RunnableConfig(callbacks=[cb], **config)):

    #     print(f"OUTPUT:\n{msg.content} ENDOF ReviewAgent\n")
        
    #     if (
    #         msg.content
    #         #and not isinstance(msg, HumanMessage)
    #         and metadata["langgraph_node"] == "final"
    #     ):
    #         #debug final_answer
    #         print(f"FINAL ANSWER1: {msg.content}")
    #         print(f"FINAL ANSWER2: {final_answer}")
    #         await final_answer.stream_token(msg.content)
    #         print(f"FINAL ANSWER3: {final_answer}")
    final_answer = cl.Message(msg["messages"][-1].content)
    print(f"FINAL ANSWER4: {final_answer}")
    await final_answer.send()