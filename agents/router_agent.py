from langchain_core.messages import SystemMessage
from dotenv import load_dotenv

from agents.state import AgentState
from core.llm import llm

load_dotenv()


_STATION_KEYWORDS = (
    "relay", "quạt", "quat", "bơm", "bom", "đèn", "den", "cảm biến",
    "cam bien", "độ ẩm", "do am", "nhiệt độ", "nhiet do", "sht31",
    "ads1115", "kết nối", "ket noi", "chế độ", "che do", "sensor",
    "pump", "fan", "light", "control mode", "connected",
)


def _is_station_question(question: str) -> bool:
    normalized = question.casefold()
    return any(keyword in normalized for keyword in _STATION_KEYWORDS)

def router_agent(state: AgentState) -> AgentState:
    # Hardware observations are already present in trusted system context. Route
    # these locally instead of spending a slow provider request on classification.
    if _is_station_question(state.get("question", "")):
        state["route"] = "chat"
        print("Router: station question -> chat")
        return state

    system_prompt = SystemMessage(
        content = """
        Classify the user's question into one of these intents:
        - chat: greetings or clarifying the already-detected disease in the system context
        - rag: tomato plant disease knowledge (symptoms, causes, prevention, treatments)
        - web: only if the question is clearly outside plant/plant-disease/agriculture topics

        Hard rules:
        0) Questions about this station's current sensor readings, connection, control mode or relay states => chat. These observations are in the system context. Never claim to actuate hardware.
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
