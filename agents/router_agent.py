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

def router_agent(state: AgentState) -> AgentState:
    system_prompt = SystemMessage(
        content = """
        Classify the user's question into one of these intents:
        - chat: greetings or clarifying the already-detected disease in the system context
        - rag: tomato plant disease knowledge (symptoms, causes, prevention, treatments)
        - web: only if the question is clearly outside plant/plant-disease/agriculture topics

        Hard rules:
        1) If the system context mentions a detected plant disease or scientific name, prefer chat, NOT web.
        2) Questions about the detected disease name, meaning, symptoms, treatment, or care => rag.
        3) Greetings or meta questions about the conversation => chat.
        4) Route to web ONLY for non-plant topics (e.g., human health, finance, weather).

        Answer with exactly one token: chat, rag, or web.
        """
    )

    messages = [system_prompt] + state["messages"]
    response = llm.invoke(messages)

    route = response.content.strip().lower().replace("\n", "").replace(" ", "")

    # Only allow valid routes
    if route not in ["chat", "rag", "web"]:
        print(f"⚠️ Router returned invalid route: {repr(route)}. Defaulting to 'rag'.")
        route = "rag"

    state["route"] = route
    print(f"🔀 Router: Routed to {state['route']}")
    return state