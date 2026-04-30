import React, { useState, useRef } from 'react';

const StockPlaylist = ({ stocks, currentIndex, onSelect, onAdd, onDelete, onSave, onImport }) => {
  const [newStock, setNewStock] = useState('');
  const [saveStatus, setSaveStatus] = useState('');
  const fileInputRef = useRef(null);

  const handleAdd = (e) => {
    e.preventDefault();
    const id = newStock.trim().toUpperCase();
    if (id) {
      onAdd(id);
      setNewStock('');
    }
  };

  const handleSave = async () => {
    await onSave(stocks);
    setSaveStatus('已儲存!');
    setTimeout(() => setSaveStatus(''), 2000);
  };

  const handleImport = (e) => {
    const file = e.target.files[0];
    if (file) onImport(file);
    e.target.value = '';
  };

  return (
    <div style={{
      background: 'var(--card-bg)',
      backdropFilter: 'blur(10px)',
      border: '1px solid var(--card-border)',
      borderRadius: '12px',
      padding: '1rem',
      display: 'flex',
      flexDirection: 'column',
      gap: '0.75rem',
      height: 'calc(100vh - 10rem)',
      position: 'sticky',
      top: '1rem',
      minWidth: '200px',
    }}>
      <h3 style={{ margin: 0, fontSize: '1.1rem', color: 'var(--text-color)' }}>
        自選股票 ({stocks.length})
      </h3>

      {/* Add stock input */}
      <form onSubmit={handleAdd} style={{ display: 'flex', gap: '0.5rem' }}>
        <input
          type="text"
          placeholder="新增股票代碼 (e.g. 2330)"
          value={newStock}
          onChange={e => setNewStock(e.target.value)}
          style={{ flex: 1, fontSize: '0.85rem', padding: '0.4rem 0.75rem' }}
        />
        <button type="submit" className="btn" style={{ padding: '0.4rem 0.8rem', fontSize: '1.1rem' }}>+</button>
      </form>

      {/* Stock list */}
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
        {stocks.length === 0 ? (
          <p style={{ color: 'var(--secondary-color)', fontSize: '0.85rem', textAlign: 'center', marginTop: '2rem' }}>
            尚無股票。請新增或匯入 CSV。
          </p>
        ) : (
          stocks.map((id, index) => (
            <div
              key={`${id}-${index}`}
              style={{
                display: 'flex',
                alignItems: 'center',
                background: index === currentIndex ? 'var(--primary-color)' : 'rgba(255,255,255,0.05)',
                borderRadius: '6px',
                padding: '0.45rem 0.6rem',
                gap: '0.5rem',
                transition: 'background 0.15s',
              }}
            >
              <button
                onClick={() => onSelect(index)}
                style={{
                  flex: 1,
                  background: 'none',
                  border: 'none',
                  color: 'white',
                  textAlign: 'left',
                  cursor: 'pointer',
                  fontWeight: index === currentIndex ? 'bold' : 'normal',
                  fontSize: '0.95rem',
                  padding: 0,
                }}
              >
                {id}
              </button>
              <button
                onClick={() => onDelete(index)}
                title="刪除"
                style={{
                  background: 'none',
                  border: 'none',
                  color: index === currentIndex ? 'rgba(255,255,255,0.8)' : 'rgba(255,255,255,0.35)',
                  cursor: 'pointer',
                  fontSize: '1.1rem',
                  padding: '0 0.2rem',
                  lineHeight: 1,
                  flexShrink: 0,
                }}
              >
                ×
              </button>
            </div>
          ))
        )}
      </div>

      {/* Bottom actions */}
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button
          className="btn"
          onClick={handleSave}
          style={{ flex: 1, fontSize: '0.85rem' }}
        >
          {saveStatus || '儲存 CSV'}
        </button>
        <label
          className="btn"
          style={{ flex: 1, fontSize: '0.85rem', background: 'var(--secondary-color)', textAlign: 'center', cursor: 'pointer' }}
        >
          匯入 CSV
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            onChange={handleImport}
            style={{ display: 'none' }}
          />
        </label>
      </div>
    </div>
  );
};

export default StockPlaylist;
