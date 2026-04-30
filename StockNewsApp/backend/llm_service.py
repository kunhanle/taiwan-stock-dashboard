import os
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from dotenv import load_dotenv

def get_llm():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    load_dotenv(env_path) 
    
    api_key_openai = os.getenv("OPENAI_API_KEY")
    api_key_google = os.getenv("GOOGLE_API_KEY")
    
    # print(f"DEBUG: Loading env from {env_path}", flush=True)
    # print(f"DEBUG: OpenAI Key present: {bool(api_key_openai)}", flush=True)
    # print(f"DEBUG: Google Key present: {bool(api_key_google)}", flush=True)
    
    if api_key_openai:
        return ChatOpenAI(api_key=api_key_openai, model="gpt-3.5-turbo")
    elif api_key_google:
        return ChatGoogleGenerativeAI(google_api_key=api_key_google, model="gemini-2.0-flash")
    else:
        # Fallback or Mock if no key provided
        print("Warning: No LLM API Key found. Returning mock LLM.")
        return None

def process_news_item(text: str) -> str:
    llm = get_llm()
    if not llm:
        return '{"summary": "Summary not available", "title_zh": ""}'
        
    prompt = ChatPromptTemplate.from_template(
        """You are a financial news assistant.
        1. Summarize the following news snippet/title into a concise, single sentence in English.
        2. Translate the news title (or main idea) into Traditional Chinese (Taiwan user context).
        
        Return the result as a raw JSON object with keys "summary" and "title_zh". Do NOT wrap in markdown code blocks.
        
        News Text: {text}"""
    )
    chain = prompt | llm | StrOutputParser()
    
    try:
        return chain.invoke({"text": text})
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"LLM Error: {e}")
        return '{"summary": "Error generating summary", "title_zh": ""}'
