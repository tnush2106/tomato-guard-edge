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


def unified_grader_answer_agent(state: AgentState) -> AgentState:
    route = state.get("route")

    # =========================
    # RAG PATH (grade + answer)
    # =========================
    if route == "rag":
        context_list = state.get("retrieved_docs", [])

        if not context_list:
            print("⚠️ No RAG content available.")
            state["enough_info"] = False
            return state

        grader_prompt = SystemMessage(
            content=f"""
You are a relevance grader.

Context:
{context_list}

Question:
{state['question']}

Does the context fully answer the question?
Reply ONLY with 'yes' or 'no'.
"""
        )

        grade_response = llm.invoke([grader_prompt])
        enough_info = grade_response.content.strip().lower() == "yes"
        state["enough_info"] = enough_info

        print(f"📊 Grader result: {'enough info' if enough_info else 'NOT enough info'}")

        if not enough_info:
            return state  # graph will handle fallback

        answer_prompt = SystemMessage(
            content=f"""
Use the following context to answer the question concisely.

Context:
{context_list}

Question:
{state['question']}
"""
        )

        final_response = llm.invoke([answer_prompt])
        state["final_answer"] = final_response.content.strip()
        return state

    # =========================
    # WEB PATH (answer only)
    # =========================
    elif route == "web":
        state['enough_info'] = None
        context_list = state.get("web_retrievals", [])

        if not context_list:
            state["final_answer"] = "No relevant web information found."
            print("Information not retrieved from the web")
            state['enough_info'] = None
            return state

        answer_prompt = SystemMessage(
            content=f"""
Use the following web search results to answer the question clearly and concisely.

Web Results:
{context_list}

Question:
{state['question']}
"""
        )

        final_response = llm.invoke([answer_prompt])
        state["final_answer"] = final_response.content.strip()
        return state

    # =========================
    # CHAT / FALLBACK
    # =========================
    else:
        return state