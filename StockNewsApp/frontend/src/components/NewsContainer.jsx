import React from 'react';
import NewsCard from './NewsCard';

const NewsContainer = ({ news, loading, error }) => {
    if (loading) {
        return (
            <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--secondary-color)' }}>
                <div className="loader" style={{ fontSize: '2rem', marginBottom: '1rem' }}>⟳</div>
                <p>Fetching latest insights...</p>
            </div>
        );
    }

    if (error) {
        return (
            <div style={{ textAlign: 'center', padding: '3rem', color: '#ef4444' }}>
                <p>Error: {error}</p>
            </div>
        );
    }

    if (!news || news.length === 0) {
        return (
            <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--secondary-color)' }}>
                <p>No news found or select a stock to begin.</p>
            </div>
        );
    }

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {news.map((item, index) => (
                <NewsCard key={`${item.link}-${index}`} news={item} />
            ))}
        </div>
    );
};

export default NewsContainer;
