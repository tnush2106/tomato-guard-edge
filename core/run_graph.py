from core.build_graph import build_graph
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

app = build_graph()

def run_graph(user_input: str, messages=None, system_context: str | None = None):
    print("In the run graph")
    messages = list(messages or [])

    # Sensor/relay observations change every turn; do not retain a stale snapshot.
    if system_context:
        messages = [m for m in messages if not isinstance(m, SystemMessage)]
        messages.insert(0, SystemMessage(content=system_context))

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
