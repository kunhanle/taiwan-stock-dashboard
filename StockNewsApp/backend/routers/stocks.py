from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List
import csv
import io
import os

router = APIRouter()

STOCKS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stocks.csv")


def read_stocks() -> List[str]:
    if not os.path.exists(STOCKS_FILE):
        return []
    stocks = []
    with open(STOCKS_FILE, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if not row or not row[0].strip():
                continue
            value = row[0].strip()
            if i == 0 and value.lower() == "stock_id":
                continue  # skip header
            stocks.append(value)
    return stocks


def write_stocks(stocks: List[str]):
    with open(STOCKS_FILE, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["stock_id"])
        for s in stocks:
            writer.writerow([s])


class StockListRequest(BaseModel):
    stocks: List[str]


@router.get("")
def get_stocks():
    return {"stocks": read_stocks()}


@router.post("/save")
def save_stocks(request: StockListRequest):
    write_stocks(request.stocks)
    return {"message": "Saved", "count": len(request.stocks)}


@router.get("/download")
def download_stocks():
    stocks = read_stocks()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["stock_id"])
    for s in stocks:
        writer.writerow([s])
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=stocks.csv"},
    )
