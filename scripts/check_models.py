from dotenv import load_dotenv
import os
from google import genai
load_dotenv()

if not os.getenv("GOOGLE_API_KEY"):
    raise SystemExit("GOOGLE_API_KEY not set — check .env")

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

print("=== Visible to this key ===")
for m in client.models.list():
    actions = getattr(m, "supported_actions", None) or []
    if "generateContent" in actions or "embedContent" in actions:
        print(f"  {m.name:45} {actions}")

print("\n=== Live probes ===")
for model in ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash",
              "gemini-3-flash-preview", "gemini-flash-latest", "gemini-flash-lite-latest"]:
    try:
        client.models.generate_content(model=model, contents="ping")
        print(f"  OK    {model}")
    except Exception as e:
        print(f"  FAIL  {model}: {type(e).__name__}: {str(e)[:110]}")

try:
    client.models.embed_content(model="gemini-embedding-001", contents="ping")
    print("  OK    gemini-embedding-001")
except Exception as e:
    print(f"  FAIL  gemini-embedding-001: {type(e).__name__}: {str(e)[:110]}")
