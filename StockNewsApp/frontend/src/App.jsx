import { useState, useEffect, useRef } from 'react';
import Header from './components/Header';
import NewsContainer from './components/NewsContainer';
import StockPlaylist from './components/StockPlaylist';
import './styles/App.css';

const API = 'http://localhost:8000';
const ITEMS_PER_PAGE = 50;

function App() {
  const [stockList, setStockList] = useState([]);
  const [stockIndex, setStockIndex] = useState(-1);
  const [newsData, setNewsData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalItems, setTotalItems] = useState(0);
  const [stockName, setStockName] = useState('');

  const today = new Date().toISOString().split('T')[0];
  const threeDaysAgo = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
  const [startDate, setStartDate] = useState(threeDaysAgo);
  const [endDate, setEndDate] = useState(today);

  // Use refs so async callbacks always see latest dates
  const startDateRef = useRef(startDate);
  const endDateRef = useRef(endDate);
  useEffect(() => { startDateRef.current = startDate; }, [startDate]);
  useEffect(() => { endDateRef.current = endDate; }, [endDate]);

  // Track in-flight request so we can cancel stale ones
  const abortRef = useRef(null);

  const currentStockId = stockIndex >= 0 && stockIndex < stockList.length
    ? stockList[stockIndex]
    : '';

  // ── Core fetch function ──────────────────────────────────────────────────
  const fetchNews = async (id, page = 1) => {
    if (!id) return;

    // Cancel any previous in-flight request
    if (abortRef.current) abortRef.current.abort();
    abortRef.current = new AbortController();
    const signal = abortRef.current.signal;

    setLoading(true);
    setError(null);
    try {
      const url = `${API}/api/news/${id}?page=${page}&limit=${ITEMS_PER_PAGE}`
        + `&start_date=${startDateRef.current}&end_date=${endDateRef.current}`;
      const res = await fetch(url, { signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setNewsData(data.items || []);
      setTotalItems(data.total || 0);
      setCurrentPage(data.page || page);
      setStockName(data.stock_name || '');
    } catch (err) {
      if (err.name === 'AbortError') return; // stale request, ignore
      setError(err.message);
      setNewsData([]);
      setStockName('');
    } finally {
      if (!signal.aborted) setLoading(false);
    }
  };

  // ── Load stock list from CSV on mount ────────────────────────────────────
  useEffect(() => {
    fetch(`${API}/api/stocks`)
      .then(r => r.json())
      .then(data => {
        const list = data.stocks || [];
        setStockList(list);
        if (list.length > 0) {
          setStockIndex(0);
          fetchNews(list[0], 1);
        }
      })
      .catch(() => setStockList([]));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Stock management ─────────────────────────────────────────────────────
  const handleSelectStock = (index) => {
    setStockIndex(index);
    setCurrentPage(1);
    setStockName('');
    fetchNews(stockList[index], 1);
  };

  const handleAddStock = (id) => {
    if (!id || stockList.includes(id)) return;
    setStockList(prev => [...prev, id]);
  };

  const handleDeleteStock = (index) => {
    setStockList(prev => {
      const next = prev.filter((_, i) => i !== index);
      if (stockIndex === index) {
        setStockIndex(-1);
        setNewsData([]);
        setStockName('');
      } else if (stockIndex > index) {
        setStockIndex(si => si - 1);
      }
      return next;
    });
  };

  const handleSaveStocks = async (list) => {
    await fetch(`${API}/api/stocks/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stocks: list }),
    });
  };

  const handleImportCSV = async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch(`${API}/api/news/upload_csv`, { method: 'POST', body: formData });
      const data = await res.json();
      if (data.stock_ids?.length > 0) {
        setStockList(data.stock_ids);
        setStockIndex(0);
        setCurrentPage(1);
        fetchNews(data.stock_ids[0], 1);
      }
    } catch (err) {
      console.error('Import failed', err);
    }
  };

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div className="app-container">
      <Header />
      <div className="main-content">

        <div className="left-panel">
          <StockPlaylist
            stocks={stockList}
            currentIndex={stockIndex}
            onSelect={handleSelectStock}
            onAdd={handleAddStock}
            onDelete={handleDeleteStock}
            onSave={handleSaveStocks}
            onImport={handleImportCSV}
          />
        </div>

        <div className="right-panel">
          <div className="news-session">

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '1rem' }}>
              <h2 style={{ fontSize: '1.5rem', fontWeight: 'bold', margin: 0 }}>
                {currentStockId
                  ? `${currentStockId}${stockName ? ` (${stockName})` : ''}`
                  : '請選擇股票'}
              </h2>
            </div>

            {/* Date range + Update */}
            <div style={{ display: 'flex', gap: '1rem', alignItems: 'flex-end', marginBottom: '1rem', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--secondary-color)' }}>Start Date</label>
                <input
                  type="date"
                  value={startDate}
                  onChange={e => setStartDate(e.target.value)}
                  style={{ padding: '0.5rem', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)', background: 'rgba(255,255,255,0.05)', color: 'white' }}
                />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--secondary-color)' }}>End Date</label>
                <input
                  type="date"
                  value={endDate}
                  onChange={e => setEndDate(e.target.value)}
                  style={{ padding: '0.5rem', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)', background: 'rgba(255,255,255,0.05)', color: 'white' }}
                />
              </div>
              <button
                className="btn"
                disabled={!currentStockId}
                onClick={() => {
                  setCurrentPage(1);
                  // sync refs immediately before async call
                  startDateRef.current = startDate;
                  endDateRef.current = endDate;
                  fetchNews(currentStockId, 1);
                }}
              >
                Update
              </button>
            </div>

            <NewsContainer news={newsData} loading={loading} error={error} />

            {!loading && totalItems > ITEMS_PER_PAGE && (
              <div style={{ display: 'flex', justifyContent: 'center', gap: '1rem', marginTop: '2rem' }}>
                <button className="btn" disabled={currentPage === 1}
                  onClick={() => fetchNews(currentStockId, currentPage - 1)}>
                  Previous
                </button>
                <span style={{ display: 'flex', alignItems: 'center', color: 'var(--secondary-color)' }}>
                  Page {currentPage} / {Math.ceil(totalItems / ITEMS_PER_PAGE)}
                </span>
                <button className="btn" disabled={currentPage * ITEMS_PER_PAGE >= totalItems}
                  onClick={() => fetchNews(currentStockId, currentPage + 1)}>
                  Next
                </button>
              </div>
            )}

          </div>
        </div>

      </div>
    </div>
  );
}

export default App;
