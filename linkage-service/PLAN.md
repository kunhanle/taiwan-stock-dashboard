# US–TW Linkage Feature — Project Plan

> 美股主題異動 → 台股供應鏈節點「讀數」的連動引擎。
> 疊加在既有 taiwan-stock-dashboard（FastAPI backend + frontend）之上。
>
> 設計核心（見 `seed/us_categories.yaml` header）：當某美股類別的龍頭大幅異動時，
> linkage 引擎依供應鏈角色（up/down/peer）把異動映射到對應台股節點，產出方向讀數。

## 架構現況
- **既有 app**：FastAPI backend（finlab 抓台股、yfinance 抓美股、`correlation_analysis.py` 算歷史相關、
  SQLModel/SQLite DB、已接 Claude/Gemini）+ frontend + 部署設定（render/vercel/docker）。
- **既有 `Category`/`CategoryStock` 表 = 使用者自訂台股分組**，與本功能的「美股主題分類」是不同概念，
  故 linkage 另建獨立資料表，不沿用、不污染既有表。

## 步驟總覽（7 步，核心 MVP = 2–5）

| # | 步驟 | 內容 | 狀態 |
|---|------|------|------|
| 1 | Seed taxonomy + validation | `seed/us_categories.yaml`（41類/148美股/80台股）、`validate_tickers.py`、驗證報告、`dual` role | ✅ 完成 |
| 2 | Data model + seed ingest | 新增 linkage 資料表（UsCategory / UsCategoryTicker / TwLinkageNode）；`ingest` 把 YAML 灌進 DB（冪等）；`role==dual` 標記 `exclude_from_scoring` | ✅ 完成 |
| 3 | Linkage engine（核心） | ① 美股類別「龍頭異動」聚合 ② 依 role 加權映射台股節點（排除 dual）③ 日報酬相關度（**美股落後1日**對齊台股時區）當權重 ④ 套用投資原則：pure-play 加權、弱訊號類別降權 | ✅ 完成 |
| 4 | Backend API | `/linkage/movers`（今日觸發類別）、`/linkage/category/{slug}`、`/linkage/stock/{tw_id}`（反查驅動主題）；接既有 TTL 快取 | 🔨 進行中 |
| 5 | Frontend UI | 連動儀表板：美股類別漲跌榜 → 下鑽台股節點；台股反查；整合進既有 frontend | ⬜ |
| 6 | 資料更新 + 排程 | 每日刷新美股收盤/台股；定期重跑 `validate_tickers.py` 抓下市漂移（如 JNPR）；接既有 `monitor/` 排程 | ⬜ |
| 7 | 部署 + 收尾 | render/vercel/docker 上線；環境變數（注意 `FINLAB_API_TOKEN` 的 `#` 截斷問題）；煙霧測試 | ⬜ |

**可選第 8 步（加值）**：用既有 Claude/Gemini 生成敘事讀數（例：「AVGO +8% 客製 ASIC → 留意欣興3037 載板」）+ 透過既有 monitor 推播警報。

## 關鍵設計約束
- **`dual` role 必須排除於關聯計分**：TSM↔2330、UMC↔2303 是同一公司雙重掛牌，算進去是自我相關、會虛胖訊號。
  ingest 在 DB 層標 `exclude_from_scoring=True`，引擎（步驟 3）據此略過。
- **弱訊號類別**：`medical-devices`、`aerospace-defense` 台股節點僅 1 檔，關聯弱，引擎應降權或標註。
- **pure-play 加權**：純度低的節點（如 ev-battery 的台泥1101）訊號應折減。
- **下市漂移**：ticker 會下市（JNPR→HPE 已修），步驟 6 需排程定期重驗。
- **資料新鮮度（重要）**：yfinance 歷史日線會「單檔零星」漏填最新一根（NaN），
  靜默 dropna 會誤用 T-1 收盤、漏掉最新異動（觀察到 MOD 2026-06-18）。
  引擎 `_repair_latest()` 用即時報價 `fast_info.last_price` 回填並 WARNING。
  根因＝別信單一 feed 的「最後一根」當最新值；步驟 6/7 應改用可靠 EOD 源並
  與即時端點交叉驗證。殘留限制：整段最新交易日全缺時需市場行事曆才能補（未做）。

## 進度紀錄
- 2026-06-18  Step 1 完成：seed + 驗證腳本 + 報告；JNPR→HPE 修正；yfinance 重試防限流；
  新增 `dual` role 並補 6 檔台股節點（華邦電/旺宏/光聖/上詮/中興電/亞力）。
- 2026-06-19  Step 2 完成：linkage 資料表（models.py）+ 冪等 ingest（ingest_linkage.py）；
  dual 列標 exclude_from_scoring；驗證 41 類/189 US 邊/160 TW 邊/2 dual。
- 2026-06-19  Step 3 完成：linkage_engine.py（compute_movers / stock_readthrough）；
  日報酬相關+美股落後1日對齊時區（corr 0.1→0.3-0.44 驗證有效）；dual 排除、
  pure-play 折減（PURITY_OVERRIDES）、弱訊號降權；台股代號 .TW/.TWO 解析+快取。
- 2026-06-20  資料新鮮度修補 `_repair_latest`（yfinance 單檔漏填最新K棒→即時報價回填）；
  全市場 228 檔 ×2 次交叉稽核（39 美股 stale 皆可修、台股全 clean）。
- 2026-06-20  半導體 cluster 改用 **SOX 偏相關**權重（Semi Manufacturing/Chip Design）：
  raw corr 多為費半 sector beta（美股籃 vs SOX 0.77-0.92），partial 扣掉費半留子類專屬。
  回歸驗證：memory 廠 partial≈+0.32-0.36 保留、WFE→晶圓廠 partial 轉負→read-through 歸0、
  台積在各類 partial≈0（它就是費半）。負 partial 視為 0；非半導體類維持 raw。
  節點輸出加 corr_raw/corr_sox/method 供前端對照。
