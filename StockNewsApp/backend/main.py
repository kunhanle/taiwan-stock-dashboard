from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
from routers import news, stocks, financials

load_dotenv()

app = FastAPI(title="Stock News API")

# CORS
origins = [
    "http://localhost:5173",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(news.router, prefix="/api/news", tags=["news"])
app.include_router(stocks.router, prefix="/api/stocks", tags=["stocks"])
app.include_router(financials.router, prefix="/api/financials", tags=["financials"])

@app.get("/")
def read_root():
    return {"message": "Stock News API is running"}
