from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from financials import router as financials_router
from finlab import data, login
import pandas as pd
import datetime
import os
import time
from functools import wraps
import json
from pydantic import BaseModel
from typing import Optional, List
from correlation_analysis import analyze_correlation
import google.generativeai as genai
import anthropic
from dotenv import load_dotenv

# Database Imports
from sqlmodel import Session, select
from database import get_session
from models import Category, CategoryStock, StockAnnotation

# Load environment variables
load_dotenv()

# Configure Gemini API
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# Configure Anthropic (Claude) client
anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY")) if os.getenv("ANTHROPIC_API_KEY") else None

app = FastAPI()

# === Simple TTL Cache ===
class TTLCache:
    """Simple in-memory cache with time-to-live."""
    def __init__(self):
        self._cache = {}
    
    def get(self, key: str, ttl_seconds: int = 300):
        """Get value if exists and not expired."""
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < ttl_seconds:
                return value
            del self._cache[key]
        return None
    
    def set(self, key: str, value):
        """Store value with current timestamp."""
        self._cache[key] = (value, time.time())
    
    def clear(self):
        """Clear all cached data."""
        self._cache.clear()

cache = TTLCache()
CACHE_TTL = 600  # 10 minutes

@app.on_event("startup")
def on_startup():
    from database import create_db_and_tables
    create_db_and_tables()

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve Frontend
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
async def read_index():
    return FileResponse(os.path.join(frontend_dir, 'index.html'))

# FinLab Login
API_TOKEN = os.getenv("FINLAB_API_TOKEN")
if API_TOKEN:
    login(api_token=API_TOKEN)
else:
    print("Warning: FINLAB_API_TOKEN not found. FinLab features will be unavailable.")

def get_market_breadth():
    # Fetch data for a longer period to accommodate rolling windows
    print("Fetching data...")
    close = data.get('price:收盤價')
    
    valid_symbols = [s for s in close.columns if len(s) == 4 and s.isdigit() and int(s) >= 1101]
    close = close[valid_symbols]
    
    close = close.ffill()

    # Calculate Indicators
    window_52w = 250
    rolling_max_52w = close.rolling(window=window_52w).max()
    rolling_min_52w = close.rolling(window=window_52w).min()
    
    is_near_high = (close >= (rolling_max_52w * 0.95))
    is_near_low = (close <= (rolling_min_52w * 1.05))
    
    window_13w = 65
    ma_13w = close.rolling(window=window_13w).mean()
    
    above_13w_ma = (close > ma_13w)
    below_13w_ma = (close < ma_13w)
    
    ma_52w = close.rolling(window=window_52w).mean()
    
    above_52w_ma = (close > ma_52w)
    below_52w_ma = (close < ma_52w)
    
    margin_today = data.get('margin_transactions:融資今日餘額')
    margin_balance_total = data.get('margin_balance:融資券總餘額')
    
    margin_balance_total = margin_balance_total.loc[margin_today.index.intersection(margin_balance_total.index)]
    
    margin_total_amt = margin_balance_total[['上市融資交易金額','上櫃融資交易金額']].sum(axis=1)
    margin_val_market = (margin_today * close * 1000).sum(axis=1) 
    
    maintenance_ratio = (margin_val_market / margin_total_amt)
    
    # Williams Vix Fix (WVF)
    taiex_low = data.get('taiex_total_index:最低指數')
    taiex_close = data.get('taiex_total_index:收盤指數')
    
    t_low = taiex_low.iloc[:, 0]
    t_close = taiex_close.iloc[:, 0]
    
    n_wvf = 22
    highest_close_22 = t_close.rolling(window=n_wvf).max()
    wvf = ((highest_close_22 - t_low) / highest_close_22) * 100
    
    n_bb = 20
    wvf_mean = wvf.rolling(window=n_bb).mean()
    wvf_std = wvf.rolling(window=n_bb).std()
    wvf_upper = wvf_mean + (2.5 * wvf_std)
    
    daily_stats = pd.DataFrame({
        'new_high_52w': is_near_high.sum(axis=1),
        'new_low_52w': is_near_low.sum(axis=1),
        'above_13w_ma': above_13w_ma.sum(axis=1),
        'below_13w_ma': below_13w_ma.sum(axis=1),
        'above_52w_ma': above_52w_ma.sum(axis=1),
        'below_52w_ma': below_52w_ma.sum(axis=1),
        'maintenance_ratio': maintenance_ratio,
        'wvf': wvf,
        'wvf_upper': wvf_upper
    })

    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=730)
    
    daily_stats = daily_stats[daily_stats.index >= start_date]
    
    daily_stats = daily_stats.reset_index()
    daily_stats['date'] = daily_stats['date'].astype(str)
    
    # Daily Change Distribution
    pct_change = close.pct_change() * 100
    latest_changes = pct_change.iloc[-1].dropna()
    latest_date_str = str(pct_change.index[-1].date())
    
    import numpy as np
    bins = np.floor(latest_changes).clip(-10, 10).astype(int)
    dist_counts = bins.value_counts().sort_index()
    
    full_range = range(-10, 11)
    distribution_data = []
    for i in full_range:
        count = int(dist_counts.get(i, 0))
        distribution_data.append({"bin": f"{i}%", "count": count, "value": i})
        
    return {
        "history": daily_stats.to_dict(orient='records'),
        "distribution": {
            "date": latest_date_str,
            "data": distribution_data
        }
    }

# --- Database Helper --- (Replaces load_categories)
def load_categories_from_db(session: Session):
    categories = {}
    cats = session.exec(select(Category)).all()
    for cat in cats:
        # Load stocks
        # Assuming eager load or lazy load works. With SQLModel, default is lazy.
        # But access will trigger.
        stocks = [item.stock_id for item in cat.stocks]
        if stocks:
            categories[cat.name] = stocks
    return categories

@app.get("/api/category-stats")
def get_category_stats(date: str = None, session: Session = Depends(get_session)):
    # 1. Load Categories from DB
    categories = load_categories_from_db(session)
    if not categories:
        return {"error": "No categories found in database"}

    # 2. Fetch Data
    print("Fetching Category Data...")
    close = data.get("price:收盤價")
    vol = data.get("price:成交股數")

    # Metrics
    pct_change_1d = close.pct_change(periods=1) * 100
    pct_change_5d = close.pct_change(periods=5) * 100 

    vol_roll5 = vol.rolling(5).mean()
    vol_jump_1d = vol / vol_roll5
    
    vol_roll3 = vol.rolling(3).mean()
    vol_roll10 = vol.rolling(10).mean()
    vol_jump_3d = vol_roll3 / vol_roll10

    pct_change_3d = close.pct_change(periods=3)
    pct_change_9d = close.pct_change(periods=9)
    pct_change_17d = close.pct_change(periods=17)

    rs = (pct_change_3d * 2) + pct_change_9d + pct_change_17d
    rs_rank = rs.rank(axis=1, pct=True) * 100

    # Medium-term RS baseline for delta: 20d×2 + 60d + 120d, percentile-ranked
    pct_change_20d  = close.pct_change(periods=20)
    pct_change_60d  = close.pct_change(periods=60)
    pct_change_120d = close.pct_change(periods=120)

    rs_lt = (pct_change_20d * 2) + pct_change_60d + pct_change_120d
    rs_rank_lt = rs_lt.rank(axis=1, pct=True) * 100

    if date:
        try:
            target_date = pd.to_datetime(date)
            if target_date not in close.index:
                available_dates = close.index
                nearest_idx = available_dates.get_indexer([target_date], method='nearest')[0]
                target_date = available_dates[nearest_idx]
            date_idx = close.index.get_loc(target_date)
        except Exception as e:
            print(f"Error parsing date: {e}")
            target_date = close.index[-1]
            date_idx = -1
    else:
        target_date = close.index[-1]
        date_idx = -1
    
    latest_pct_1d = pct_change_1d.iloc[date_idx]
    latest_pct_5d = pct_change_5d.iloc[date_idx]
    latest_vol_jump_1d = vol_jump_1d.iloc[date_idx]
    latest_vol_jump_3d = vol_jump_3d.iloc[date_idx]
    latest_rs_rank    = rs_rank.iloc[date_idx]
    latest_rs_rank_lt = rs_rank_lt.iloc[date_idx]

    cat_metrics = []

    for cat_name, stocks in categories.items():
        valid_stocks = [s for s in stocks if s in close.columns]
        if not valid_stocks:
            continue

        val_1d = latest_pct_1d[valid_stocks].mean()
        val_5d = latest_pct_5d[valid_stocks].mean()

        stocks_vol_1d = latest_vol_jump_1d[valid_stocks]
        count_vol_1d = (stocks_vol_1d > 2).sum()
        ratio_vol_1d = count_vol_1d / len(valid_stocks)

        stocks_vol_3d = latest_vol_jump_3d[valid_stocks]
        count_vol_3d = (stocks_vol_3d > 2).sum()
        ratio_vol_3d = count_vol_3d / len(valid_stocks)

        val_rs_rank    = latest_rs_rank[valid_stocks].mean()
        val_rs_rank_lt = latest_rs_rank_lt[valid_stocks].mean()
        val_rs_delta   = (
            (val_rs_rank - val_rs_rank_lt)
            if not pd.isna(val_rs_rank) and not pd.isna(val_rs_rank_lt)
            else 0
        )

        cat_metrics.append({
            "name": cat_name,
            "avg_change_1d": val_1d if not pd.isna(val_1d) else 0,
            "avg_change_5d": val_5d if not pd.isna(val_5d) else 0,
            "vol_jump_1d_count": int(count_vol_1d),
            "vol_jump_1d_ratio": ratio_vol_1d,
            "vol_jump_3d_count": int(count_vol_3d),
            "vol_jump_3d_ratio": ratio_vol_3d,
            "avg_rs_rank": val_rs_rank if not pd.isna(val_rs_rank) else 0,
            "avg_rs_delta": val_rs_delta,
            "stock_count": len(valid_stocks)
        })

    table1 = sorted(cat_metrics, key=lambda x: x['avg_change_1d'], reverse=True)[:10]
    table2 = sorted(cat_metrics, key=lambda x: x['avg_change_5d'], reverse=True)[:10]
    table3 = [x for x in cat_metrics if x['vol_jump_1d_ratio'] > 0.5]
    table4 = [x for x in cat_metrics if x['vol_jump_3d_ratio'] > 0.5]
    table5 = sorted(cat_metrics, key=lambda x: x['avg_rs_rank'], reverse=True)[:10]
    table6 = sorted(
        [x for x in cat_metrics if x['avg_rs_rank'] >= 70],
        key=lambda x: x['avg_rs_delta'], reverse=True
    )[:10]

    available_dates = [d.strftime('%Y-%m-%d') for d in close.index[-60:]]

    return {
        "date": str(target_date.date()),
        "available_dates": available_dates,
        "table1": table1,
        "table2": table2,
        "table3": table3,
        "table4": table4,
        "table5": table5,
        "table6": table6
    }

@app.get("/api/category-details/{category_name}")
def get_category_details(category_name: str, session: Session = Depends(get_session)):
    categories = load_categories_from_db(session)
    if category_name not in categories:
        return {"error": "Category not found"}
        
    stock_ids = categories[category_name]
    
    close = data.get("price:收盤價")
    open_ = data.get("price:開盤價")
    high = data.get("price:最高價")
    low = data.get("price:最低價")
    volume = data.get("price:成交股數")
    
    company_info = data.get('company_basic_info').set_index('stock_id')
    
    close = close.iloc[-250:]
    open_ = open_.iloc[-250:]
    high = high.iloc[-250:]
    low = low.iloc[-250:]
    volume = volume.iloc[-250:]
    
    stock_data = {}
    for sid in stock_ids:
        if sid in close.columns:
            try:
                stock_name = company_info.loc[sid]['公司簡稱'] if sid in company_info.index else sid
            except:
                stock_name = sid
            
            df = pd.DataFrame({
                'date': close.index,
                'open': open_[sid],
                'high': high[sid],
                'low': low[sid],
                'close': close[sid],
                'volume': volume[sid] if sid in volume.columns else 0
            }).dropna()
            
            df['date'] = df['date'].dt.strftime('%Y-%m-%d')
            stock_data[sid] = {
                'name': stock_name,
                'data': df.to_dict(orient='records')
            }
            
    return {
        "category": category_name,
        "stocks": stock_data
    }

class BatchStockRequest(BaseModel):
    stock_ids: list[str]

@app.post("/api/batch-stock-data")
def get_batch_stock_data(req: BatchStockRequest):
    stock_ids = req.stock_ids
    if not stock_ids:
        return {"stocks": {}}

    close = data.get("price:收盤價")
    open_ = data.get("price:開盤價")
    high = data.get("price:最高價")
    low = data.get("price:最低價")
    volume = data.get("price:成交股數")
    
    company_info = data.get('company_basic_info').set_index('stock_id')
    
    close = close.iloc[-250:]
    open_ = open_.iloc[-250:]
    high = high.iloc[-250:]
    low = low.iloc[-250:]
    volume = volume.iloc[-250:]
    
    stock_data = {}
    for sid in stock_ids:
        if sid in close.columns:
            try:
                stock_name = company_info.loc[sid]['公司簡稱'] if sid in company_info.index else sid
            except:
                stock_name = sid

            df = pd.DataFrame({
                'date': close.index,
                'open': open_[sid],
                'high': high[sid],
                'low': low[sid],
                'close': close[sid],
                'volume': volume[sid] if sid in volume.columns else 0
            }).dropna()
            
            df['date'] = df['date'].dt.strftime('%Y-%m-%d')
            
            stock_data[sid] = {
                'name': stock_name,
                'data': df.to_dict(orient='records')
            }
            
    return {"stocks": stock_data}

@app.get("/api/market-stats")
def market_stats():
    # Check cache first
    cached = cache.get("market_stats", CACHE_TTL)
    if cached:
        print("Returning cached market_stats")
        return cached
    
    # Fetch fresh data
    result = get_market_breadth()
    cache.set("market_stats", result)
    return result

@app.get("/api/preset-levels")
def get_preset_levels(session: Session = Depends(get_session)):
    try:
        annotations = session.exec(select(StockAnnotation)).all()
        stocks = []
        for a in annotations:
            levels = []
            if a.levels_json:
                levels = [float(x) for x in a.levels_json.split(',') if x.strip()]
            elif a.level_1 is not None:
                # Migrate legacy fields on read
                for v in [a.level_1, a.level_2, a.level_3]:
                    if v is not None:
                        levels.append(v)
            stocks.append({
                "stock_id": a.stock_id,
                "take_profit": a.take_profit,
                "levels": levels
            })
        return {"stocks": stocks}
    except Exception as e:
        print(f"Error reading levels: {e}")
        return {"stocks": []}

class SaveContentRequest(BaseModel):
    content: str

class StockLevelItem(BaseModel):
    stock_id: str
    take_profit: Optional[float] = None
    levels: List[float] = []

class SaveLevelsRequest(BaseModel):
    stocks: List[StockLevelItem]

@app.post("/api/save-levels")
def save_preset_levels(req: SaveLevelsRequest, session: Session = Depends(get_session)):
    try:
        submitted_ids = set()
        for item in req.stocks:
            sid = item.stock_id.strip()
            if not sid:
                continue
            submitted_ids.add(sid)
            annot = session.get(StockAnnotation, sid)
            if not annot:
                annot = StockAnnotation(stock_id=sid)
            annot.take_profit = item.take_profit if item.take_profit and item.take_profit > 0 else None
            valid_levels = [l for l in item.levels if l > 0]
            annot.levels_json = ','.join(str(l) for l in valid_levels) if valid_levels else None
            session.add(annot)

        # Delete annotations not in the submitted list (true sync)
        all_annotations = session.exec(select(StockAnnotation)).all()
        for a in all_annotations:
            if a.stock_id not in submitted_ids:
                session.delete(a)

        session.commit()
        return {"status": "success"}
    except Exception as e:
        print(f"Error saving file: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/preset-sma")
def get_preset_sma(session: Session = Depends(get_session)):
    try:
        annotations = session.exec(select(StockAnnotation)).all()
        lines = []
        for a in annotations:
            if a.sma_short is not None and a.sma_long is not None:
                lines.append(f"{a.stock_id},{a.sma_short},{a.sma_long}")
        content = "\n".join(lines)
        return {"content": content}
    except Exception as e:
        print(f"Error reading SMA file: {e}")
        return {"content": ""}

@app.post("/api/save-sma")
def save_preset_sma(req: SaveContentRequest, session: Session = Depends(get_session)):
    try:
        lines = req.content.strip().split('\n')
        for line in lines:
            line = line.strip()
            if not line: continue
            parts = line.split(',')
            if len(parts) >= 3:
                sid = parts[0].strip()
                try:
                    short = int(parts[1])
                    long_ = int(parts[2])
                    
                    annot = session.get(StockAnnotation, sid)
                    if not annot:
                        annot = StockAnnotation(stock_id=sid)
                    
                    annot.sma_short = short
                    annot.sma_long = long_
                    session.add(annot)
                except ValueError:
                    continue
        session.commit()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

class ExtractLevelsRequest(BaseModel):
    text: str
    model: Optional[str] = None

@app.post("/api/extract-levels")
def extract_levels(req: ExtractLevelsRequest):
    import json, re
    try:
        prompt = f"""你是一個台股技術分析助手。請從以下分析文字中，提取出最關鍵的價格數字。

**停利點**：文字中的「目標價」、「樂觀目標」、「短期/中期目標」、「壓力位」、「滿足點」等最高合理目標價。優先選取短期或中期目標，而非極端的長期估值。

**Level 1（第一道防線）**：最靠近現價的支撐位，例如「層級一」、「情緒支撐」、「短期支撐」、「第一支撐」。
**Level 2（第二道防線）**：第二道支撐，例如「層級二」、「溫和支撐」、「中期支撐」。
**Level 3（第三道防線）**：更深的支撐，例如「層級三」、「熊市支撐」、「年線支撐」、「底部區域」。

規則：
- 支撐位必須 L1 > L2 > L3（由高到低排列）
- 若某層不存在，回傳 null
- 只擷取文字中明確提及的數字，不要推算或猜測
- 只回傳 JSON，不要有任何說明文字

格式：{{"take_profit": 數字或null, "level_1": 數字或null, "level_2": 數字或null, "level_3": 數字或null}}

分析文字：
{req.text}"""

        available = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        if req.model and req.model in available:
            model_name = req.model
        else:
            model_name = next((m for m in available if 'flash' in m.lower()), available[0] if available else None)
        if not model_name:
            return {"error": "No Gemini model available"}

        print(f"extract-levels using model: {model_name}")
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
        raw = response.text.strip()
        print(f"Gemini extract-levels raw: {raw}")

        match = re.search(r'\{[^{}]+\}', raw)
        if not match:
            return {"error": "無法從回應中解析 JSON", "raw": raw}
        data = json.loads(match.group())

        levels = []
        for key in ["level_1", "level_2", "level_3"]:
            v = data.get(key)
            if v is not None:
                try:
                    levels.append(float(v))
                except (TypeError, ValueError):
                    pass

        tp = data.get("take_profit")
        try:
            tp = float(tp) if tp is not None else None
        except (TypeError, ValueError):
            tp = None

        return {"take_profit": tp, "levels": levels}
    except Exception as e:
        print(f"Extract levels error: {e}")
        return {"error": str(e)}

class AnalyzeRequest(BaseModel):
    stock_ids: list[str]
    metal: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None

@app.post("/api/analyze")
def api_analyze(req: AnalyzeRequest):
    try:
        results = analyze_correlation(
            stock_ids=req.stock_ids,
            metal_name=req.metal,
            start_date=req.start_date,
            end_date=req.end_date
        )
        return results
    except Exception as e:
        print(f"Analysis error: {e}")
        return {"error": str(e)}

@app.get("/api/ai-models")
def get_ai_models():
    try:
        models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                models.append(m.name)
        return {"models": models}
    except Exception as e:
        return {"error": str(e), "models": []}

class AiSummaryRequest(BaseModel):
    date: str
    model: str = "models/gemini-1.5-flash"

@app.post("/api/ai-summary")
def get_ai_summary(req: AiSummaryRequest, session: Session = Depends(get_session)):
    try:
        target_date = pd.to_datetime(req.date)
        print(f"Generating summary for {req.date}...")
        
        taiex_close = data.get('taiex_total_index:收盤指數')
        try:
            taiex_vol = data.get('taiex_total_index:成交值')
        except:
             try:
                 taiex_vol = data.get('taiex_total_index:成交金額')
             except:
                 taiex_vol = None
        
        close = data.get('price:收盤價')
        
        try:
            foreign_inv = data.get('institutional_investors:外資及陸資買賣超')
        except:
            foreign_inv = None
            
        try:
            investment_trust = data.get('institutional_investors:投信買賣超')
        except:
            investment_trust = None
            
        try:
            dealer = data.get('institutional_investors:自營商買賣超')
        except:
            dealer = None
        
        categories = load_categories_from_db(session)
        
        if target_date not in taiex_close.index:
             idx_loc = taiex_close.index.get_indexer([target_date], method='pad')[0]
             if idx_loc == -1:
                 return {"error": "Date out of range"}
             target_date = taiex_close.index[idx_loc]
             
        date_str = str(target_date.date())
        
        t_c = taiex_close.loc[target_date].iloc[0]
        prev_date = taiex_close.index[taiex_close.index.get_loc(target_date) - 1]
        t_c_prev = taiex_close.loc[prev_date].iloc[0]
        index_change = t_c - t_c_prev
        
        if taiex_vol is not None and target_date in taiex_vol.index:
             index_vol = taiex_vol.loc[target_date].iloc[0]
             vol_str = f"{index_vol/1e8:.2f} 億"
        else:
             vol_str = "N/A"
        
        key_stocks = {'2330': '台積電', '2317': '鴻海', '2454': '聯發科'}
        key_stock_perf = []
        for sid, name in key_stocks.items():
            if sid in close.columns:
                p_now = close.loc[target_date, sid]
                p_prev = close.loc[prev_date, sid]
                diff = p_now - p_prev
                key_stock_perf.append(f"{name}({sid}): Price {p_now} (Diff {diff:.1f})")

        try:
            mkt_foreign = data.get('institutional_investors_trading_summary:外資及陸資買賣超')
            mkt_trust = data.get('institutional_investors_trading_summary:投信買賣超')
            mkt_dealer = data.get('institutional_investors_trading_summary:自營商買賣超')
            
            f_val = mkt_foreign.loc[target_date].iloc[0] if target_date in mkt_foreign.index else 0
            t_val = mkt_trust.loc[target_date].iloc[0] if target_date in mkt_trust.index else 0
            d_val = mkt_dealer.loc[target_date].iloc[0] if target_date in mkt_dealer.index else 0
        except:
             f_val = foreign_inv.loc[target_date].sum() if (foreign_inv is not None and target_date in foreign_inv.index) else 0
             t_val = investment_trust.loc[target_date].sum() if (investment_trust is not None and target_date in investment_trust.index) else 0
             d_val = dealer.loc[target_date].sum() if (dealer is not None and target_date in dealer.index) else 0
             
        inst_summary = f"外資: {f_val/1e8:.2f}億, 投信: {t_val/1e8:.2f}億, 自營商: {d_val/1e8:.2f}億"

        cat_gains = []
        pct_change_1d = close.pct_change() * 100
        latest_pct = pct_change_1d.loc[target_date]
        
        for cat_name, stocks in categories.items():
            valid_s = [s for s in stocks if s in close.columns]
            if valid_s:
                avg_gain = latest_pct[valid_s].mean()
                cat_gains.append((cat_name, avg_gain, valid_s))
        
        cat_gains.sort(key=lambda x: x[1], reverse=True)
        top_cats = cat_gains[:3]
        
        top_cat_str = ""
        for name, gain, stocks in top_cats:
             stock_gains = latest_pct[stocks].sort_values(ascending=False)
             top_s = stock_gains.index[0]
             top_s_val = stock_gains.iloc[0]
             top_cat_str += f"- {name}: Avg Gain {gain:.2f}%. Leader: {top_s} ({top_s_val:.2f}%)\n"

        prompt = f"""
請扮演一名資深的台股分析師。請針對 {date_str} 的台股表現進行盤後總結。

【市場數據】
- 大盤日期: {date_str}
- 加權指數收盤: {t_c} (漲跌: {index_change})
- 成交量: {vol_str}
- 三大權值股表現: {', '.join(key_stock_perf)}
- 三大法人買賣超: {inst_summary}
- 強勢族群(漲幅前三):
{top_cat_str}

【分析任務】
1. 大盤走勢： 指數漲跌點數、成交量變化、以及盤中關鍵的轉折時間點(若無分時數據請略過轉折點)。
2. 三類權值股表現： 台積電（晶圓代工）、鴻海（代工）、聯發科（IC設計）對大盤的貢獻度。
3. 資金流向： 今天的資金集中在哪些電子族群（如 AI、半導體、散熱）？是否有流向非電族群（如重電、航運、生技）？
4. 外資與投信動態： 根據三大法人買賣超數據，判斷法人目前的態度是偏多、偏空還是觀望。
5. 結論： 今天的盤勢對下一個交易日有什麼啟示？請列出 3 個觀察重點

B. 分析今天台股盤面上的 『熱門題材族群』。請執行以下任務：
6. 列出今天漲幅前三名的族群(參考上方數據)，並解釋背後的推動因素（例如：國際大廠消息、法說會預期、報價上漲等，請根據你的知識庫補充合理原因）。
觀察這些族群中，哪些股票是**『領頭羊』（漲最快或率先漲停），哪些是『跟漲股』**？
也列出美股或日股中相關族群的股票，以及該股票當天的新聞跟走勢，如果有連動關係請註明。
分析這些熱門族群的成交量是否異常放大？這代表是短線投機熱錢，還是長線法人布局？
針對這些族群，請評估其題材的續航力（是一日行情還是週趨勢？）
"""
        
        print(f"Prompt constructed. Calling Gemini with model {req.model}...")
        try:
            model = genai.GenerativeModel(req.model)
        except Exception:
            available = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            fallback = next((m for m in available if 'flash' in m.lower()), available[0] if available else None)
            if not fallback:
                return {"error": "No Gemini model available"}
            print(f"Model {req.model} failed, falling back to {fallback}")
            model = genai.GenerativeModel(fallback)

        response = model.generate_content(prompt)
        
        return {"summary": response.text, "date": date_str}
        
    except Exception as e:
        print(f"Error generating summary: {e}")
        return {"error": str(e)}

# ──────────────────────────────────────────────────────────
# Stock News Feature
# ──────────────────────────────────────────────────────────

_DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(__file__))
NEWS_WATCHLIST_FILE = os.path.join(_DATA_DIR, "news_watchlist.csv")

def _load_news_watchlist():
    try:
        if os.path.exists(NEWS_WATCHLIST_FILE):
            df = pd.read_csv(NEWS_WATCHLIST_FILE, dtype=str).fillna('')
            stocks = [{"id": row["id"], "name": row["name"]} for _, row in df.iterrows() if row["id"]]
            return {"stocks": stocks}
    except Exception as e:
        print(f"Error loading news watchlist: {e}")
    return {"stocks": []}

def _save_news_watchlist(watchlist_data):
    try:
        stocks = watchlist_data.get("stocks", [])
        df = pd.DataFrame(stocks if stocks else [], columns=["id", "name"])
        df.to_csv(NEWS_WATCHLIST_FILE, index=False, encoding="utf-8-sig")
    except Exception as e:
        print(f"Error saving news watchlist: {e}")

class NewsStockItem(BaseModel):
    id: str
    name: str

class NewsWatchlistRequest(BaseModel):
    stocks: List[NewsStockItem]

class FetchNewsRequest(BaseModel):
    stock_ids: List[str]
    days: int = 7

@app.get("/api/news-watchlist")
def get_news_watchlist():
    return _load_news_watchlist()

@app.post("/api/news-watchlist")
def save_news_watchlist_endpoint(req: NewsWatchlistRequest):
    watchlist_data = {"stocks": [{"id": s.id, "name": s.name} for s in req.stocks]}
    _save_news_watchlist(watchlist_data)
    return {"status": "success"}

@app.get("/api/stock-name/{stock_id}")
def get_stock_name_endpoint(stock_id: str):
    try:
        if any(c.isalpha() for c in stock_id):
            return {"stock_id": stock_id, "name": None}
        df = data.get('company_basic_info')
        if df is not None:
            matches = df[df['stock_id'] == stock_id]
            if not matches.empty:
                name = str(matches.iloc[0]['公司簡稱'])
                return {"stock_id": stock_id, "name": name}
    except Exception as e:
        print(f"Error getting stock name for {stock_id}: {e}")
    return {"stock_id": stock_id, "name": None}

@app.post("/api/fetch-news")
def fetch_stock_news(req: FetchNewsRequest):
    import urllib.request
    from urllib.parse import quote
    import xml.etree.ElementTree as ET
    import datetime as dt

    company_info = None
    try:
        df = data.get('company_basic_info')
        if df is not None:
            company_info = df.set_index('stock_id')
    except Exception as e:
        print(f"Error loading company info: {e}")

    def is_us_stock(sid):
        return any(c.isalpha() for c in sid)

    def get_name(sid):
        if company_info is None or is_us_stock(sid):
            return None
        try:
            if sid in company_info.index:
                return str(company_info.loc[sid]['公司簡稱'])
        except Exception:
            pass
        return None

    def fetch_finlab_news(stock_id, days):
        """Fetch Taiwan stock news from FinLab tw_news_cnyes (indexed by stock_id)."""
        news_list = []
        try:
            df_news = data.get('tw_news_cnyes')
            if df_news is None or df_news.empty:
                return []
            regex_pat = f'(^|,){stock_id}(,|$)'
            mask = df_news['stock_ids'].astype(str).str.contains(regex_pat, regex=True, na=False)
            filtered = df_news[mask].copy()
            if filtered.empty:
                return []
            filtered['date'] = pd.to_datetime(filtered['date'])
            cutoff = dt.datetime.now() - dt.timedelta(days=days)
            filtered = filtered[filtered['date'] >= cutoff]
            for _, row in filtered.iterrows():
                news_list.append({
                    "title": str(row['title']),
                    "link": str(row['url']),
                    "date": row['date'].strftime("%Y-%m-%d %H:%M"),
                    "source": "鉅亨網"
                })
            news_list.sort(key=lambda x: x['date'], reverse=True)
            print(f"FinLab news: {len(news_list)} articles for {stock_id}")
        except Exception as e:
            print(f"Error fetching FinLab news for {stock_id}: {e}")
        return news_list

    def get_real_article_date(url):
        """Fetch article page and extract real publication date from meta tags."""
        import re as _re
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            req_obj = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req_obj, timeout=4) as resp:
                html = resp.read(8192).decode("utf-8", errors="replace")
            # Open Graph article:published_time
            m = _re.search(r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']', html, _re.I)
            if not m:
                m = _re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']', html, _re.I)
            if m:
                return pd.to_datetime(m.group(1), utc=True).to_pydatetime().replace(tzinfo=None)
            # JSON-LD datePublished
            m = _re.search(r'"datePublished"\s*:\s*"([^"]+)"', html)
            if m:
                return pd.to_datetime(m.group(1), utc=True).to_pydatetime().replace(tzinfo=None)
            # <time datetime="...">
            m = _re.search(r'<time[^>]+datetime=["\']([^"\']+)["\']', html, _re.I)
            if m:
                return pd.to_datetime(m.group(1), utc=True).to_pydatetime().replace(tzinfo=None)
        except Exception:
            pass
        return None

    def filter_by_real_date(articles, days):
        """Parallel-fetch each article to verify its real publication date."""
        import concurrent.futures
        cutoff = dt.datetime.now() - dt.timedelta(days=days)

        def check(article):
            real_dt = get_real_article_date(article["link"])
            if real_dt is not None:
                if real_dt < cutoff:
                    return None  # confirmed stale — drop
                article["date"] = real_dt.strftime("%Y-%m-%d %H:%M")
            # real_dt is None → can't verify → keep with RSS date
            return article

        valid = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            for result in ex.map(check, articles):
                if result is not None:
                    valid.append(result)
        return valid

    def fetch_google_news_rss_tw(query, days, keyword=None):
        """Google News RSS for Taiwan stocks with title filtering and real-date validation."""
        full_query = f"{query} when:{days}d"
        url = f"https://news.google.com/rss/search?q={quote(full_query)}&hl=zh-TW&gl=TW&ceid=TW:zh-TW"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        req_obj = urllib.request.Request(url, headers=headers)
        raw_articles = []
        try:
            with urllib.request.urlopen(req_obj, timeout=15) as resp:
                content = resp.read()
            root = ET.fromstring(content)
            seen = set()
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link = item.findtext("link", "").strip()
                pub_date = item.findtext("pubDate", "").strip()
                source_el = item.find("source")
                source = source_el.text.strip() if source_el is not None and source_el.text else "Google News"
                if not title or not link or link in seen:
                    continue
                # Only keep articles where the stock name appears in the title
                if keyword and keyword not in title:
                    continue
                seen.add(link)
                raw_articles.append({"title": title, "link": link, "date": pub_date, "source": source})
            print(f"Google News RSS raw: {len(raw_articles)} articles for '{query}' (after title filter)")
        except Exception as e:
            print(f"Google News RSS error for '{query}': {e}")
        return filter_by_real_date(raw_articles, days)

    def fetch_uanalyze_news(stock_name, days):
        """Fetch articles from UAnalyze XML feed filtered by stock name in title."""
        articles = []
        cutoff_ms = int((dt.datetime.now() - dt.timedelta(days=days)).timestamp() * 1000)
        try:
            url = "https://uanalyze.com.tw/feeds/articles"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            req_obj = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req_obj, timeout=10) as resp:
                content = resp.read()
            root = ET.fromstring(content)
            for article in root.findall(".//article"):
                title = article.findtext("title", "").strip()
                pub_ts_ms = int(article.findtext("publishTimeUnix", "0").strip() or 0)
                src_url = article.findtext("sourceUrl", "").strip()
                if not title or not src_url or stock_name not in title or pub_ts_ms < cutoff_ms:
                    continue
                pub_dt = dt.datetime.fromtimestamp(pub_ts_ms / 1000)
                articles.append({
                    "title": title,
                    "link": src_url,
                    "date": pub_dt.strftime("%Y-%m-%d %H:%M"),
                    "source": "UAnalyze"
                })
            print(f"UAnalyze: {len(articles)} articles for {stock_name}")
        except Exception as e:
            print(f"Error fetching UAnalyze news: {e}")
        return articles

    def fetch_trendforce_news(stock_name, days):
        """Scrape TrendForce presscenter page filtered by stock name in title."""
        import re as _re
        articles = []
        cutoff = dt.datetime.now() - dt.timedelta(days=days)
        try:
            url = "https://www.trendforce.com.tw/presscenter"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            req_obj = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req_obj, timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            pattern = r'href="(/presscenter/news/(\d{8})-\d+\.html)"[^>]*>.*?<strong>(.*?)</strong>'
            seen = set()
            for link, date_str, title in _re.findall(pattern, html, _re.DOTALL):
                title = _re.sub(r"<[^>]+>", "", title).strip()
                if not title or link in seen or stock_name not in title:
                    continue
                try:
                    pub_dt = dt.datetime.strptime(date_str, "%Y%m%d")
                except Exception:
                    continue
                if pub_dt < cutoff:
                    continue
                seen.add(link)
                articles.append({
                    "title": title,
                    "link": f"https://www.trendforce.com.tw{link}",
                    "date": pub_dt.strftime("%Y-%m-%d"),
                    "source": "TrendForce"
                })
            print(f"TrendForce: {len(articles)} articles for {stock_name}")
        except Exception as e:
            print(f"Error fetching TrendForce news: {e}")
        return articles

    def parse_rss_date(pub_date_str):
        from email.utils import parsedate_to_datetime
        try:
            return parsedate_to_datetime(pub_date_str).replace(tzinfo=None)
        except Exception:
            try:
                return pd.to_datetime(pub_date_str, utc=True).to_pydatetime().replace(tzinfo=None)
            except Exception:
                return None

    def fetch_site_rss(rss_url, source_name, days, keyword=None):
        """Generic RSS fetcher with strict server-side date filtering."""
        articles = []
        cutoff = dt.datetime.now() - dt.timedelta(days=days)
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            req_obj = urllib.request.Request(rss_url, headers=headers)
            with urllib.request.urlopen(req_obj, timeout=10) as resp:
                content = resp.read()
            root = ET.fromstring(content)
            seen = set()
            for item in root.findall(".//item"):
                title = item.findtext("title", "").strip()
                link = item.findtext("link", "").strip()
                pub_date_str = item.findtext("pubDate", "").strip()
                if not title or not link or link in seen:
                    continue
                if keyword and keyword not in title:
                    continue
                pub_dt = parse_rss_date(pub_date_str)
                if pub_dt is None or pub_dt < cutoff:
                    continue
                seen.add(link)
                articles.append({
                    "title": title,
                    "link": link,
                    "date": pub_dt.strftime("%Y-%m-%d %H:%M"),
                    "source": source_name
                })
            print(f"{source_name}: {len(articles)} articles")
        except Exception as e:
            print(f"Error fetching {source_name} ({rss_url}): {e}")
        return articles

    def fetch_google_news_rss(query, lang, country, ceid, days):
        """Google News RSS — used for US stocks only."""
        full_query = f"{query} when:{days}d"
        url = f"https://news.google.com/rss/search?q={quote(full_query)}&hl={lang}&gl={country}&ceid={ceid}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        req_obj = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req_obj, timeout=15) as resp:
            content = resp.read()
        root = ET.fromstring(content)
        articles = []
        seen = set()
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            pub_date = item.findtext("pubDate", "").strip()
            source_el = item.find("source")
            source = source_el.text.strip() if source_el is not None and source_el.text else ""
            if title and link and link not in seen:
                seen.add(link)
                articles.append({"title": title, "link": link, "date": pub_date, "source": source})
        return articles

    def merge_articles(base, additions):
        seen = {a['link'] for a in base}
        for a in additions:
            if a['link'] not in seen:
                base.append(a)
                seen.add(a['link'])
        return base

    results = {}
    for stock_id in req.stock_ids:
        try:
            is_us = is_us_stock(stock_id)
            stock_name = get_name(stock_id)
            articles = []

            if is_us:
                articles = fetch_google_news_rss(f"{stock_id} stock", "en", "US", "US:en", req.days)
            else:
                # FinLab (鉅亨網) — primary source, indexed by stock_id
                articles = fetch_finlab_news(stock_id, req.days)

                # MoneyDJ — per-stock RSS, strict date filtering
                merge_articles(articles, fetch_site_rss(
                    f"https://www.moneydj.com/rss/RssCompanyNews.aspx?stockid={stock_id}",
                    "MoneyDJ", req.days
                ))

                # UAnalyze — XML feed filtered by stock name in title
                if stock_name:
                    merge_articles(articles, fetch_uanalyze_news(stock_name, req.days))

                # TrendForce TW — scrape presscenter page filtered by stock name in title
                if stock_name:
                    merge_articles(articles, fetch_trendforce_news(stock_name, req.days))

                # Google News RSS — title must contain stock name, plus real-date validation
                gn_query = stock_name if stock_name else stock_id
                merge_articles(articles, fetch_google_news_rss_tw(gn_query, req.days, keyword=stock_name))

                articles.sort(key=lambda x: x['date'], reverse=True)

            results[stock_id] = {"name": stock_name or stock_id, "articles": articles[:50]}
            print(f"Total {len(articles)} articles for {stock_id}")
        except Exception as e:
            print(f"Error fetching news for {stock_id}: {e}")
            results[stock_id] = {"name": stock_id, "articles": [], "error": str(e)}

    return {"results": results}


app.include_router(financials_router, prefix="/api/financials", tags=["financials"])

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
