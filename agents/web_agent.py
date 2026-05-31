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
from tools.tavily_search_tool import tavily_search_tool
from agents.state import AgentState
from core.llm import llm

load_dotenv()

def web_answer_agent(state: AgentState) -> AgentState:
    """
    Answers the question by searching the Web using tool-calling.
    Stores retrieved web results separately in state['web_retrievals'].
    """

    system_prompt = SystemMessage(
        content="""
    You are a web-search assistant.
    Use the `tavily_search_tool` when you need to fetch information from the internet.
    After the tool returns results, generate the final answer using those results.
    """
    )

    # Bind tool
    llm_with_tools = llm.bind_tools([tavily_search_tool])
    state["route"] = 'web'

    # User's question
    user_message = HumanMessage(content=state["question"])

    # Step 1 — LLM decides whether to call the tool
    response = llm_with_tools.invoke([system_prompt, user_message])

    # Step 2 — Execute tool calls (same pattern as retrieve_agent)
    tool_calls = getattr(response, "tool_calls", [])
    tool_outputs = []

    for t in tool_calls:
        tool_name = t["name"]
        query = t["args"].get("query", "")

        print(f"🔧 WebAgent executing tool: {tool_name} with query: {query}")

        # Directly invoke tool function
        result = tavily_search_tool.invoke(query)
        tool_outputs.append(result)

    # Step 3 — Store web results separately
    state["web_retrievals"] = tool_outputs

    print(state)

    print("🌐 Web Answer Agent Completed")
    return state