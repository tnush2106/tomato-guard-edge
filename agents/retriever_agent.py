from typing import TypedDict, Annotated, Sequence, Optional, List, Literal
from langchain_core.messages import BaseMessage, ToolMessage, SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from dotenv import load_dotenv
import os
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode

from langchain_community.embeddings import HuggingFaceEmbeddings
from tavily import TavilyClient

from tools.retriever_tool import retriever_tool
from tools.tavily_search_tool import tavily_search_tool
from agents.state import AgentState
from core.llm import llm


load_dotenv()



tools = [retriever_tool, tavily_search_tool]

def retrieve_agent(state: AgentState) -> AgentState:
    """
    Retrieval-augmented RAG agent using tool-calling.
    """
    system_prompt = SystemMessage(
        content="""
    You are an intelligent RAG assistant for answering questions about Tomato plant diseases.
    Use the `retriever_tool` when you need to fetch knowledge from the FAISS vectorstore.
    You MUST call the tool when retrieval is needed.
    After using the tool, generate a final answer citing the retrieved text.
    """
    )

    llm_with_tools = llm.bind_tools(tools)

    user_message = state["messages"][-1]
    
    # Invoke LLM with tool access
    response = llm_with_tools.invoke([system_prompt, user_message])

    # Build tools dictionary
    tools_dict = {tool.name: tool for tool in tools}

    # Execute tool calls
    tool_results = []
    for t in getattr(response, 'tool_calls', []):
        if t['name'] in tools_dict:
            result = tools_dict[t['name']].invoke(t['args'].get('query', ''))
            tool_results.append(ToolMessage(tool_call_id=t['id'], name=t['name'], content=str(result)))
        else:
            tool_results.append(ToolMessage(tool_call_id=t['id'], name=t['name'], content="Invalid tool"))

    # Store retrieved content for grading
    if tool_results:
        state["retrieved_docs"] = [tm.content for tm in tool_results]

    print("🔧 RAG agent executed with tool-calling")
    return state
