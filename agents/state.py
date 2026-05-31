from typing import TypedDict, Annotated, Sequence, Optional, List, Literal
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    question: str
    messages: Annotated[Sequence[BaseMessage], add_messages]
    route: Optional[Literal["chat", "rag", "web"]]
    retrieved_docs: Optional[List[str]]
    web_retrievals: Optional[List[str]]
    enough_info: Optional[bool]
    final_answer: Optional[str]


