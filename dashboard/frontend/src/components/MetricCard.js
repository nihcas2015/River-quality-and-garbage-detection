import React from 'react';
import '../styles/MetricCard.css';

function MetricCard({ title, value, unit, icon: Icon, status = 'normal', trend = null }) {
  return (
    <div className={`metric-card ${status}`}>
      <div className="metric-header">
        <h3>{title}</h3>
        {Icon && <Icon size={24} className="metric-icon" />}
      </div>
      
      <div className="metric-body">
        <div className="metric-value">
          {value}
          {unit && <span className="metric-unit">{unit}</span>}
        </div>
        {trend && (
          <div className={`metric-trend ${trend > 0 ? 'up' : 'down'}`}>
            {trend > 0 ? '↑' : '↓'} {Math.abs(trend)}%
          </div>
        )}
      </div>
      
      <div className="metric-footer">
        <span className="status-indicator"></span>
        <span className="status-text">{status}</span>
      </div>
    </div>
  );
}

export default MetricCard;
