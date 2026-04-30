import React, { useState } from 'react';
import '../styles/NewsCard.css';

const NewsCard = ({ news }) => {
    const [summary, setSummary] = useState(null);
    const [titleZh, setTitleZh] = useState(news.title_zh || "");
    const [loadingSummary, setLoadingSummary] = useState(false);

    const handleGetSummary = async () => {
        setLoadingSummary(true);
        try {
            // Construct text to summarize
            let text = news.title;
            if (news.summary && news.summary.length > 20) {
                text += ": " + news.summary;
            }

            const response = await fetch('http://localhost:8000/api/news/summary', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ text: text }),
            });

            if (response.ok) {
                const data = await response.json();
                setSummary(data.summary);
                setTitleZh(data.title_zh);
            }
        } catch (error) {
            console.error("Error fetching summary:", error);
        } finally {
            setLoadingSummary(false);
        }
    };

    return (
        <article className="news-card fade-in">
            <div className="news-header">
                <a href={news.link} target="_blank" rel="noopener noreferrer" className="news-title">
                    {news.title}
                </a>
            </div>

            {titleZh && (
                <div style={{ color: '#93c5fd', fontSize: '1.1rem', marginBottom: '0.5rem', fontWeight: 500 }}>
                    {titleZh}
                </div>
            )}

            <div className="news-meta">
                <span>{news.source}</span>
                <span>•</span>
                <span>{news.date}</span>
            </div>

            <div className="news-summary">
                {summary ? (
                    <>
                        <span className="summary-label">AI Summary</span>
                        {summary}
                    </>
                ) : loadingSummary ? (
                    <p style={{ fontStyle: 'italic', color: '#9ca3af' }}>Generating AI Summary...</p>
                ) : (
                    <button
                        onClick={handleGetSummary}
                        className="btn-summary"
                        style={{
                            marginTop: '0.5rem',
                            padding: '0.4rem 0.8rem',
                            fontSize: '0.9rem',
                            background: 'rgba(255, 255, 255, 0.1)',
                            border: '1px solid rgba(255, 255, 255, 0.2)',
                            borderRadius: '4px',
                            color: '#e5e7eb',
                            cursor: 'pointer'
                        }}
                    >
                        Get AI Summary
                    </button>
                )}
            </div>
        </article>
    );
};

export default NewsCard;
