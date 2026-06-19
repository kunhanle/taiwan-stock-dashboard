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
| 2 | Data model + seed ingest | 新增 linkage 資料表（UsCategory / UsCategoryTicker / TwLinkageNode）；`ingest` 把 YAML 灌進 DB（冪等）；`role==dual` 標記 `exclude_from_scoring` | 🔨 進行中 |
| 3 | Linkage engine（核心） | ① 美股類別「龍頭異動」聚合 ② 依 role 加權映射台股節點（排除 dual）③ 結合 `correlation_analysis.py` 歷史相關度當權重 ④ 套用投資原則：pure-play 加權、弱訊號類別降權 | ⬜ |
| 4 | Backend API | `/linkage/movers`（今日觸發類別）、`/linkage/category/{slug}`、`/linkage/stock/{tw_id}`（反查驅動主題）；接既有 TTL 快取 | ⬜ |
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

## 進度紀錄
- 2026-06-18  Step 1 完成：seed + 驗證腳本 + 報告；JNPR→HPE 修正；yfinance 重試防限流；
  新增 `dual` role 並補 6 檔台股節點（華邦電/旺宏/光聖/上詮/中興電/亞力）。
