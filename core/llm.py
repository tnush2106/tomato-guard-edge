import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

openrouter_api_key = os.getenv("OPENROUTER_API_KEY")

llm = ChatOpenAI(
    model = "openai/gpt-4o-mini",
    base_url= "https://openrouter.ai/api/v1",
    api_key = openrouter_api_key,
    temperature=0.0,
    max_tokens = 1000
)