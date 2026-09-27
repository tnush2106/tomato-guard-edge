from typing import TypedDict, Annotated, Sequence, Optional, List, Literal
from langchain_core.messages import BaseMessage, ToolMessage, SystemMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from dotenv import load_dotenv
import os
from pathlib import Path
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode

from langchain_community.embeddings import HuggingFaceEmbeddings
from tavily import TavilyClient

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

@tool
def tavily_search_tool(query: str) -> str:
    """
    Perform web scraping for the query using Tavily.
    Returns a combined string of results.
    """
    print("🌍 In Tavily Search Tool")
    try:
        tavily_api_key = os.getenv("TAVILY_API_KEY")
        if not tavily_api_key:
            return "Web search failed: Missing TAVILY_API_KEY in .env"
        tavily = TavilyClient(api_key=tavily_api_key)
        web_data = tavily.search(query, max_results=3)
        results = [r["content"] for r in web_data.get("results", [])]
        return "\n\n".join(results) if results else "No web results found."
    except Exception as e:
        return f"Web search failed: {str(e)}"
