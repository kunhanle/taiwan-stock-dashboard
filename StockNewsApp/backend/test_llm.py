import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
import traceback

try:
    load_dotenv()
    key = os.getenv("GOOGLE_API_KEY")
    print(f"Key loaded: {bool(key)}")
    if key:
        print(f"Key preview: {key[:5]}...")
    
    llm = ChatGoogleGenerativeAI(google_api_key=key, model="gemini-2.0-flash")
    print("Invoking LLM...")
    result = llm.invoke("Hello, say hi!")
    print("Result:", result.content)
except Exception:
    traceback.print_exc()
