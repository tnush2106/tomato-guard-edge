from core.build_graph import build_graph
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

app = build_graph()

def run_graph(user_input: str, messages=None, system_context: str | None = None):
    print("In the run graph")
    if messages is None:
        messages = []

    # Inject system context ONCE
    if system_context and not any(isinstance(m, SystemMessage) for m in messages):
        messages.append(SystemMessage(content=system_context))

    # Append user message (✅ FIXED)
    messages.append(HumanMessage(content=user_input))
    print("Graph fed message: ",messages)

    result = app.invoke(
        {
            "question": user_input,
            "messages": messages,
            "route": None,
            "retrieved_docs": [],
            "web_retrievals": [],
            "enough_info": None,
            "final_answer": None
        }
    )

    # Append AI response
    messages.append(AIMessage(content=result["final_answer"]))

    return result["final_answer"], messages