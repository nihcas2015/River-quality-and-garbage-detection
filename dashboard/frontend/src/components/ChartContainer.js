import React from 'react';
import '../styles/ChartContainer.css';

function ChartContainer({ title, children, loading = false, refresh = null }) {
  return (
    <div className="chart-container">
      <div className="chart-header">
        <h3>{title}</h3>
        {refresh && (
          <button className="refresh-btn" onClick={refresh} title="Refresh">
            ⟲
          </button>
        )}
      </div>
      
      <div className="chart-content">
        {loading ? (
          <div className="chart-loading">
            <div className="spinner"></div>
            <p>Loading...</p>
          </div>
        ) : (
          children
        )}
      </div>
    </div>
  );
}

export default ChartContainer;
