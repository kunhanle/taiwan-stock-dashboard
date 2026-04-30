import React from 'react';

const Header = () => {
    return (
        <header style={{ marginBottom: '1rem' }}>
            <h1 style={{
                fontSize: '2.5rem',
                fontWeight: 'bold',
                background: 'linear-gradient(to right, #60a5fa, #a78bfa)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                margin: 0
            }}>
                Stock News AI
            </h1>
            <p style={{ color: 'var(--secondary-color)', marginTop: '0.5rem' }}>
                Real-time insights powered by Google News & LLM
            </p>
        </header>
    );
};

export default Header;
