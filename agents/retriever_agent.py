from dotenv import load_dotenv

from agents.state import AgentState
from tools.retriever_tool import retriever_tool


load_dotenv()


def retrieve_agent(state: AgentState) -> AgentState:
    """Retrieve documents directly after the router selects the RAG path.

    Retrieval is mandatory here. Asking the LLM whether it should call the
    retriever only adds a slow network round trip and another failure point.
    """
    result = str(retriever_tool.invoke({"query": state["question"]})).strip()
    if result and not result.startswith("Retriever unavailable:"):
        state["retrieved_docs"] = [result]
    else:
        state["retrieved_docs"] = []

    print("RAG retrieval completed")
    return state
