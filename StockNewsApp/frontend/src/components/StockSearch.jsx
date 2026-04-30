import React, { useState } from 'react';

const StockSearch = ({ onSearch, onUpload }) => {
    const [stockId, setStockId] = useState('');

    const handleSubmit = (e) => {
        e.preventDefault();
        if (stockId.trim()) {
            onSearch(stockId.trim());
        }
    };

    const handleFileUpload = (e) => {
        const file = e.target.files[0];
        if (file) {
            onUpload(file);
        }
    };

    return (
        <div style={{
            display: 'flex',
            gap: '1rem',
            alignItems: 'center',
            background: 'var(--card-bg)',
            padding: '1rem',
            borderRadius: '12px',
            border: '1px solid var(--card-border)'
        }}>
            <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '0.5rem', flex: 1 }}>
                <input
                    type="text"
                    placeholder="Enter Stock ID (e.g., 2330)"
                    value={stockId}
                    onChange={(e) => setStockId(e.target.value)}
                    style={{ flex: 1 }}
                />
                <button type="submit" className="btn">Search</button>
            </form>

            <div style={{ width: '1px', height: '2rem', background: 'var(--card-border)' }}></div>

            <label className="btn" style={{ background: 'var(--secondary-color)', display: 'inline-flex', alignItems: 'center' }}>
                Upload CSV
                <input
                    type="file"
                    accept=".csv"
                    onChange={handleFileUpload}
                    style={{ display: 'none' }}
                />
            </label>
        </div>
    );
};

export default StockSearch;
