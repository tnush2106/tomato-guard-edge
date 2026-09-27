#!/usr/bin/env python3
"""Check the AI provider or local retrieval separately on the Raspberry Pi."""

import argparse
import os
from pathlib import Path
import sys
import time

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rag", action="store_true", help="Check local documents instead of calling the AI API")
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
    started = time.monotonic()
    try:
        if args.rag:
            print("Checking local retrieval; first use may download the embedding model...", flush=True)
            from core.faiss_setup import build_or_load_faiss
            retriever = build_or_load_faiss()
            docs = retriever.invoke("tomato late blight prevention")
            if not docs:
                raise RuntimeError("No document chunks returned")
            print(f"RAG OK: {len(docs)} chunks, {time.monotonic() - started:.1f} seconds")
        else:
            print("Checking the configured AI provider...", flush=True)
            from core.llm import llm, provider
            model = getattr(llm, "model_name", None) or getattr(llm, "model", "unknown")
            print(f"Provider: {provider}; model: {model}", flush=True)
            response = llm.invoke("Reply with only OK.")
            if not response.content:
                raise RuntimeError("AI returned empty content")
            print(f"AI API OK: {time.monotonic() - started:.1f} seconds")
    except Exception as exc:
        message = str(exc)
        for name, value in os.environ.items():
            if name.endswith("API_KEY") and value:
                message = message.replace(value, "[REDACTED]")
        print(f"FAILED after {time.monotonic() - started:.1f} seconds: {type(exc).__name__}: {message}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
