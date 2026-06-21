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
| 4 | Backend API | `linkage_api.py` router 掛 `/api/linkage`：`/categories`、`/category/{slug}`(兩層綜合)、`/movers`、`/stock/{tw_id}`；TTL 快取(30min, refresh 參數)。TestClient 驗證通過(cache 1.6s→0s) | ✅ 完成 |
| 5 | Frontend UI | 既有 React(index.html) 新增「美台連動」分頁 `LinkageView`：類別選擇器(按cluster分組)+兩層表格(A股價/讀數/B營收/領先落後/判定徽章)+台股反查。瀏覽器端到端驗證渲染正確 | ✅ 完成 |
| 6 | 資料更新 + 排程 | 每日刷新美股收盤/台股；定期重跑 `validate_tickers.py` 抓下市漂移（如 JNPR）；接既有 `monitor/` 排程 | ⬜ |
| 7 | 部署 + 收尾 | render/vercel/docker 上線；環境變數（注意 `FINLAB_API_TOKEN` 的 `#` 截斷問題）；煙霧測試 | ⬜ |

**可選第 8 步（加值）**：用既有 Claude/Gemini 生成敘事讀數（例：「AVGO +8% 客製 ASIC → 留意欣興3037 載板」）+ 透過既有 monitor 推播警報。

## 兩層架構（重要）
這個 App 有兩個本質不同的連動層，並列呈現：
- **A 讀數層（短線交易）**：美股動→台股短期跟。用**股價相關**（`linkage_engine.py`；半導體扣 SOX 偏相關）。
- **B 基本面層（景氣方向）**：誰供誰、上下游景氣同步。用**營收 YoY 連動 + 領先/落後**
  （`revenue_linkage.py`；美股季營收=SEC EDGAR、台股月營收=finlab）。
  驗證：設備鏈台股對 AMAT 營收 YoY 連動 0.5-0.83（聯電0.83/京鼎0.59/帆宣領先2季），
  股價只 0.03-0.19——景氣連動股價撈不到、營收撈得到。

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
- 2026-06-21  Step 4 完成：`linkage_api.py` FastAPI router 掛進 main.py(`/api/linkage`)，
  4 端點(categories/category/movers/stock)+TTL 快取(30min)。TestClient 驗證：
  /categories 42類、/category/{slug} 回兩層綜合 JSON、404 處理、快取 1.6s→0.00s。
- 2026-06-20  新增 `passive-components` 類（cluster=Components，非半導體）：US=VSH(+KN/CTS，美股這塊薄、龍頭多被台日併購)；TW peer=國巨2327/華新科2492/禾伸堂3026/信昌電6173/大毅2478。驗證抓到奇力新2456已下市(併入國巨)並換掉。兩層皆成立：4/5 tradeable+fundamental(A 0.22-0.24, B 0.35-0.44)。報告刷新 US 151 / TW 88 全有效。
- 2026-06-18  Step 1 完成：seed + 驗證腳本 + 報告；JNPR→HPE 修正；yfinance 重試防限流；
  新增 `dual` role 並補 6 檔台股節點（華邦電/旺宏/光聖/上詮/中興電/亞力）。
- 2026-06-19  Step 2 完成：linkage 資料表（models.py）+ 冪等 ingest（ingest_linkage.py）；
  dual 列標 exclude_from_scoring；驗證 41 類/189 US 邊/160 TW 邊/2 dual。
- 2026-06-19  Step 3 完成：linkage_engine.py（compute_movers / stock_readthrough）；
  日報酬相關+美股落後1日對齊時區（corr 0.1→0.3-0.44 驗證有效）；dual 排除、
  pure-play 折減（PURITY_OVERRIDES）、弱訊號降權；台股代號 .TW/.TWO 解析+快取。
- 2026-06-20  資料新鮮度修補 `_repair_latest`（yfinance 單檔漏填最新K棒→即時報價回填）；
  全市場 228 檔 ×2 次交叉稽核（39 美股 stale 皆可修、台股全 clean）。
- 2026-06-20  B 層精修 + 兩層綜合 `linkage_synthesis.py`：(#2)半導體類 B 改用「扣半導體營收
  共同因子(排除自身成分股)」偏相關→memory partial 存活0.47-0.67(真專屬)、GPU washout(就是大盤循環)；
  (#3)領先/落後加穩健門檻(n≥16且增益≥0.12才採信)；(#4)US 營收覆蓋率透明(缺ONON等外國發行人);
  (#5)每節點三類訊號判定：tradeable+fundamental / fundamental-only / semi-cycle / weak。
- 2026-06-20  **B 基本面層** `revenue_linkage.py`：美股季營收(SEC EDGAR XBRL frame，~8年)
  + 台股月營收(finlab)→季 YoY；每節點對類股美股營收 YoY 算同期相關+最佳領先/落後(±2季)。
  驗證 semi-wfe/memory（n≈24-33季）：聯電0.83/京鼎0.59/南亞科0.74，帆宣領先2季。
  US 營收快取+CIK map gitignore。下一步：A/B 兩層接 API + 前端並列視圖。
- 2026-06-20  半導體 cluster 改用 **SOX 偏相關**權重（Semi Manufacturing/Chip Design）：
  raw corr 多為費半 sector beta（美股籃 vs SOX 0.77-0.92），partial 扣掉費半留子類專屬。
  回歸驗證：memory 廠 partial≈+0.32-0.36 保留、WFE→晶圓廠 partial 轉負→read-through 歸0、
  台積在各類 partial≈0（它就是費半）。負 partial 視為 0；非半導體類維持 raw。
  節點輸出加 corr_raw/corr_sox/method 供前端對照。
