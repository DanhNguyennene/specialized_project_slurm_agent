from langchain.chains import LLMChain
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
#from IPython.display import Image, display
from langgraph.types import interrupt
from langgraph.checkpoint.memory import MemorySaver
from operator import add
from langgraph.types import Command
#from langchain_ollama import OllamaLLM
from langchain.schema.runnable.config import RunnableConfig
from langchain_core.messages import HumanMessage, SystemMessage, BaseMessage
from TestCaseDB.retrievalTool import retrievalBugs
from TestExecution.handleReproduceStep import handleReproduceSuggestion
from langchain_groq import ChatGroq

import chainlit as cl

#ChatLLM = OllamaLLM(base_url="http://localhost:11434", model = "qwq:32b", streaming=True)
#ChatLLM = ChatGroq(temperature=0, model_name="llama3-70b-8192")
ChatLLM = ChatGroq(temperature=0, model_name="llama-3.3-70b-versatile")

class State(TypedDict):
    messages: list[BaseMessage]
    bugDescription: str
    retrievedData: str
    reproduceSuggestion: str
    testResult: str
    reviewResult: str
    failInformation: str

def checkStopPoint(state: State):
    if "NOK" in state["reviewResult"]:
        print("\nCheckPoint NOK\n")
        return "NOK"
    print("\nCheckPoint OK\n")
    return "OK"

def BugAnalysisAgent(state: State):
    print("\n*********************BugAnalysisAgent**************************\n")
    information = state["messages"][0].content
    information = """<problem>
#ID:
26716

#bin:
ibcf 7.2.65

#Config:
[ MATCHING_RULE_HAS_TO_TAG ]
Header_Name = TO
Element_Type = HEADER-PARAM, tag
Condition_Type = NONE
Instance = "*"
Min_Occurrence = 1

#ERROR:
"W0 Apply matching rule HAS_TO_TAG : false"
</problem>"""
    return {"bugDescription": information}

def RetrievalAgent(state: State):
    print("\n*********************RetrievalAgent**************************\n")
    print("Get 2 most related bugs")
    bugDescription = state["bugDescription"]
    retrievedData = retrievalBugs(bugDescription)
    return {"retrievedData": retrievedData}

def DecisionAgent(state: State, retry=0):
    print("\n*********************DecisionAgent**************************\n")
    bugDescription, retrievedData, failInformation = "", "", ""
    bugDescription = state["bugDescription"]
    retrievedData = state["retrievedData"]
    if retry:
        failInformation = "Note: You have failed with the step bellow, so try to avoid it:\n" + state["failInformation"]

    prompt = f'''Given 2 example:
    {retrievedData}
    Based on two examples, create a list of step to reproduce the new ERROR. Only print steps, no explaination. Finish with </end>:
    """
    {bugDescription}
    """
    {failInformation}
    '''
    msg = ChatLLM.invoke([HumanMessage(content=prompt)])
    msg = msg.content
    print(msg)
    
    return {"reproduceSuggestion": msg, "messages": [msg]}

def TestAgent(state: State):
    print("\n*********************TestAgent**************************\n")
    #TODO: Trigger function call to reproduce the problem
    if "reproduceSuggestion" not in state:
        return {"testResult": "The test is NOK"}
    reproduceSuggestion = state["reproduceSuggestion"]
    testResult = handleReproduceSuggestion(reproduceSuggestion)
    return {"testResult": testResult}

def ReviewAgent(state: State):
    print("\n*********************ReviewAgent**************************\n")
    testResult = state["testResult"]
    msg = ChatLLM.invoke([
        HumanMessage(content="Review the test result is OK or NOK, only print answer: {testResult}")
    ])
    msg = msg.content
    return {"reviewResult": msg, "messages": [msg]}

workflow = StateGraph(State)
# Add nodes
workflow.add_node("BugAnalysisAgent", BugAnalysisAgent)
workflow.add_node("RetrievalAgent", RetrievalAgent)
workflow.add_node("DecisionAgent", DecisionAgent)
workflow.add_node("TestAgent", TestAgent)
workflow.add_node("ReviewAgent", ReviewAgent)
# Add edges to connect nodes
workflow.add_edge(START, "BugAnalysisAgent")
workflow.add_edge("BugAnalysisAgent", "RetrievalAgent") 
workflow.add_edge("RetrievalAgent", "DecisionAgent")
workflow.add_edge("DecisionAgent", "TestAgent")
workflow.add_edge("TestAgent", "ReviewAgent")
workflow.add_conditional_edges(
    "ReviewAgent", checkStopPoint, {"NOK": "DecisionAgent", "OK": END}
)
checkpointer = MemorySaver()
graph = workflow.compile(checkpointer=checkpointer)

# Show workflow
#display(Image(graph.get_graph().draw_mermaid_png()))
# # Invoke
# thread_config = {"configurable": {"thread_id": "1"}}
# state = graph.invoke({"bugID": 12345}, thread_config)
# #value_from_human = "This is the testing for user input"
# value_from_human = str(input())
# # Resume the graph with the human's input
# graph.invoke(Command(resume=value_from_human), config=thread_config)
# human_review = str(input())
# graph.invoke(Command(resume=human_review), config=thread_config)


@cl.on_message
async def on_message(msg: cl.Message):
    config = {"configurable": {"thread_id": cl.context.session.id}}
    cb = cl.LangchainCallbackHandler()
    final_answer = cl.Message(content="answer")
    #print(msg.content)

    for msg in graph.stream({"messages": [HumanMessage(content=msg.content)]}, stream_mode="values", config=RunnableConfig(callbacks=[cb], **config)):
        #print(f"OUTPUT:\n{msg} ENDOF ReviewAgent\n")
        _
    #print(f"FINAL ANSWER1: {msg}")
    final_answer = cl.Message(msg["reproduceSuggestion"])
    #print(f"FINAL ANSWER4: {final_answer}")
    await final_answer.send()