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
from agents.state import AgentState
from core.llm import llm

load_dotenv()

def chat_agent(state: AgentState) -> AgentState:
    system_prompt = SystemMessage(
        content="You are a friendly assistant. Respond naturally."
    )

    # Use all messages (which includes system context with disease info)
    messages = [system_prompt] + state["messages"]

    # invoke LLM
    response = llm.invoke(messages)

    # append AI response to state messages
    state["messages"] = state["messages"] + [response]

    state['final_answer'] = response.content

    print("💬 Chat response generated")
    return state

