import sys as _sys
from pathlib import Path as _Path
_ROOT = str(_Path(__file__).resolve().parents[1])
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)

from typing import TypedDict, Annotated, Sequence, Optional, List, Literal
from langchain_core.messages import BaseMessage, ToolMessage, SystemMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from dotenv import load_dotenv
import os
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode

from langchain_community.embeddings import HuggingFaceEmbeddings
from tavily import TavilyClient
from core.faiss_setup import build_or_load_faiss

load_dotenv()

@tool
def retriever_tool(query: str) -> str:
    """
    Retrieve relevant document chunks from FAISS.
    """
    print("In the Retriever tool")
    try:
        retriever = build_or_load_faiss()
        docs = retriever._get_relevant_documents(query, run_manager=None)
        return "\n\n".join([d.page_content for d in docs])
    except Exception as e:
        return f"Retriever unavailable: {str(e)}"
