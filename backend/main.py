from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from finlab import data, login
import pandas as pd
import datetime
import os
from pydantic import BaseModel
from typing import Optional, List
from correlation_analysis import analyze_correlation
import google.generativeai as genai
from dotenv import load_dotenv

# Database Imports
from sqlmodel import Session, select
from database import get_session
from models import Category, CategoryStock, StockAnnotation

# Load environment variables
load_dotenv()

# Configure Gemini API
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

app = FastAPI()

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
    latest_rs_rank = rs_rank.iloc[date_idx]

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

        val_rs_rank = latest_rs_rank[valid_stocks].mean()
        
        cat_metrics.append({
            "name": cat_name,
            "avg_change_1d": val_1d if not pd.isna(val_1d) else 0,
            "avg_change_5d": val_5d if not pd.isna(val_5d) else 0,
            "vol_jump_1d_count": int(count_vol_1d),
            "vol_jump_1d_ratio": ratio_vol_1d,
            "vol_jump_3d_count": int(count_vol_3d),
            "vol_jump_3d_ratio": ratio_vol_3d,
            "avg_rs_rank": val_rs_rank if not pd.isna(val_rs_rank) else 0,
            "stock_count": len(valid_stocks)
        })

    table1 = sorted(cat_metrics, key=lambda x: x['avg_change_1d'], reverse=True)[:10]
    table2 = sorted(cat_metrics, key=lambda x: x['avg_change_5d'], reverse=True)[:10]
    table3 = [x for x in cat_metrics if x['vol_jump_1d_ratio'] > 0.5]
    table4 = [x for x in cat_metrics if x['vol_jump_3d_ratio'] > 0.5]
    table5 = sorted(cat_metrics, key=lambda x: x['avg_rs_rank'], reverse=True)[:10]
    
    available_dates = [d.strftime('%Y-%m-%d') for d in close.index[-60:]]
    
    return {
        "date": str(target_date.date()),
        "available_dates": available_dates,
        "table1": table1,
        "table2": table2,
        "table3": table3,
        "table4": table4,
        "table5": table5
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
    data = get_market_breadth()
    return data

@app.get("/api/preset-levels")
def get_preset_levels(session: Session = Depends(get_session)):
    # Convert DB levels to CSV format to maintain frontend compatibility
    try:
        annotations = session.exec(select(StockAnnotation)).all()
        # Filter only those that have levels
        lines = []
        for a in annotations:
            if a.level_1 is not None: # Assuming if L1 exists, display. Or check any level.
                # Format: StockID, L1, L2, L3
                l1 = f"{a.level_1}" if a.level_1 is not None else ""
                l2 = f"{a.level_2}" if a.level_2 is not None else ""
                l3 = f"{a.level_3}" if a.level_3 is not None else ""
                # Avoid trailing commas if empty? The frontend likely expects numbers.
                # Replicate previous CSV format: ID, L1, L2, L3
                # Need to match strictness. If None, empty string?
                # The previous parser handled it via split.
                lines.append(f"{a.stock_id},{l1},{l2},{l3}")
        
        content = "\n".join(lines)
        return {"content": content}
    except Exception as e:
        print(f"Error reading levels: {e}")
        return {"content": ""}

class SaveLevelsRequest(BaseModel):
    content: str

@app.post("/api/save-levels")
def save_preset_levels(req: SaveLevelsRequest, session: Session = Depends(get_session)):
    try:
        # content is CSV string. Parse and update DB.
        lines = req.content.strip().split('\n')
        for line in lines:
            line = line.strip()
            if not line: continue
            parts = line.split(',')
            if len(parts) >= 4:
                sid = parts[0].strip()
                try:
                    l1 = float(parts[1]) if parts[1].strip() else None
                    l2 = float(parts[2]) if parts[2].strip() else None
                    l3 = float(parts[3]) if parts[3].strip() else None
                    
                    annot = session.get(StockAnnotation, sid)
                    if not annot:
                        annot = StockAnnotation(stock_id=sid)
                    
                    annot.level_1 = l1
                    annot.level_2 = l2
                    annot.level_3 = l3
                    session.add(annot)
                except ValueError:
                    continue
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
def save_preset_sma(req: SaveLevelsRequest, session: Session = Depends(get_session)):
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
        return {"error": str(e), "models": ["models/gemini-1.5-flash"]}

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
        except:
             print(f"Model {req.model} failed, falling back to gemini-1.5-flash")
             model = genai.GenerativeModel('gemini-1.5-flash')

        response = model.generate_content(prompt)
        
        return {"summary": response.text, "date": date_str}
        
    except Exception as e:
        print(f"Error generating summary: {e}")
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
