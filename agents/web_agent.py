from agents.state import AgentState
from tools.tavily_search_tool import tavily_search_tool


def web_answer_agent(state: AgentState) -> AgentState:
    """Run web retrieval directly after the router selects the web path."""
    state["route"] = "web"
    result = str(tavily_search_tool.invoke({"query": state["question"]})).strip()
    if result and not result.startswith("Web search failed:"):
        state["web_retrievals"] = [result]
    else:
        state["web_retrievals"] = []

    print("Web retrieval completed")
    return state
