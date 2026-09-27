import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

def _usable_key(name, prefixes=()):
    value = os.getenv(name, "").strip()
    if not value or value.lower().startswith(("your_", "replace_", "sk-your")):
        return None
    if prefixes and not value.startswith(prefixes):
        return None
    return value


provider = os.getenv("LLM_PROVIDER", "auto").strip().lower()
openrouter_key = _usable_key("OPENROUTER_API_KEY", ("sk-or-",))
openai_key = _usable_key("OPENAI_API_KEY", ("sk-",))
google_key = _usable_key("GOOGLE_API_KEY")


def _positive_float(name, default):
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _non_negative_int(name, default):
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


# Bound every remote call so a slow provider cannot outlive the dashboard request.
request_timeout = _positive_float("LLM_REQUEST_TIMEOUT", 30)
max_retries = _non_negative_int("LLM_MAX_RETRIES", 0)

if provider == "auto":
    provider = "openrouter" if openrouter_key else "openai" if openai_key else "google" if google_key else ""

if provider == "openrouter" and openrouter_key:
    llm = ChatOpenAI(
        model=os.getenv("OPENROUTER_MODEL", "openrouter/free"),
        base_url="https://openrouter.ai/api/v1",
        api_key=openrouter_key,
        temperature=0.0,
        max_tokens=1000,
        timeout=request_timeout,
        max_retries=max_retries,
        default_headers={"HTTP-Referer": "https://tvhuynh.click", "X-OpenRouter-Title": "TomatoGuard"},
    )
elif provider == "openai" and openai_key:
    llm = ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        api_key=openai_key,
        temperature=0.0,
        max_tokens=1000,
        timeout=request_timeout,
        max_retries=max_retries,
    )
elif provider == "google" and google_key:
    from langchain_google_genai import ChatGoogleGenerativeAI

    llm = ChatGoogleGenerativeAI(
        model=os.getenv("GOOGLE_MODEL", "gemini-1.5-flash"),
        google_api_key=google_key,
        temperature=0.0,
        max_output_tokens=1000,
    )
else:
    raise RuntimeError(
        "LLM is not configured. Set LLM_PROVIDER and its matching API key in Software/.env"
    )
