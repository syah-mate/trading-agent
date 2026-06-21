# python/test_openrouter.py
import httpx, os
from dotenv import load_dotenv
load_dotenv()

key = os.getenv("OPENROUTER_API_KEY")
print(f"Key loaded: {key[:20]}...")

r = httpx.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers={"Authorization": f"Bearer {key}"},
    json={
        "model": "x-ai/grok-4.3",
        "messages": [{"role": "user", "content": "ping"}]
    }
)
print(r.status_code)
print(r.json())