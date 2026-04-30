from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import List
import pandas as pd
import io
from news_service import get_stock_news, get_stock_name
from llm_service import process_news_item
import json

router = APIRouter()

class NewsItem(BaseModel):
    title: str
    date: str
    source: str
    link: str
    summary: str
    title_zh: str = ""

class StockRequest(BaseModel):
    stock_id: str

class NewsResponse(BaseModel):
    items: List[NewsItem]
    total: int
    page: int
    limit: int
    stock_name: str

class SummaryRequest(BaseModel):
    text: str

class SummaryResponse(BaseModel):
    summary: str
    title_zh: str

@router.post("/summary", response_model=SummaryResponse)
async def generate_summary(request: SummaryRequest):
    try:
        llm_result_json = process_news_item(request.text)
        # Clean up potential markdown formatting
        llm_result_json = llm_result_json.replace("```json", "").replace("```", "").strip()
        
        try:
           llm_data = json.loads(llm_result_json)
           return SummaryResponse(
               summary=llm_data.get("summary", "No summary available"),
               title_zh=llm_data.get("title_zh", "")
           )
        except json.JSONDecodeError:
           return SummaryResponse(
               summary=llm_result_json,
               title_zh=""
           )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{stock_id}", response_model=NewsResponse)
async def get_news(stock_id: str, page: int = 1, limit: int = 50, start_date: str = None, end_date: str = None):
    try:
        raw_news = get_stock_news(stock_id, start_date=start_date, end_date=end_date)
        total_count = len(raw_news)
        
        # Pagination Logic
        start_index = (page - 1) * limit
        end_index = start_index + limit
        sliced_news = raw_news[start_index:end_index]
        
        processed_news = []
        for item in sliced_news:
            # Skip automatic LLM processing for speed
            # Return raw summary (description) and empty title_zh
            
            processed_news.append(NewsItem(
                title=item['title'],
                date=item['date'],
                source=item['source'],
                link=item['link'],
                summary=item['summary'] if item.get('summary') else "",
                title_zh="" # Client will fetch this on demand
            ))
            
        return NewsResponse(
            items=processed_news,
            total=total_count,
            page=page,
            limit=limit,
            stock_name=get_stock_name(stock_id) or ""
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload_csv")
async def upload_csv(file: UploadFile = File(...)):
    # Expect CSV with 'stock_id' column
    contents = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(contents))
        if 'stock_id' not in df.columns:
            # Try first column
            stock_ids = df.iloc[:, 0].astype(str).tolist()
        else:
            stock_ids = df['stock_id'].astype(str).tolist()
            
        # This endpoint might just return the IDs, or fetch news for all?
        # Fetching for all might be very slow.
        # Ideally, we return the IDs and the frontend fetches news for each sequentially or in parallel.
        return {"stock_ids": stock_ids}
        
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid CSV file")
