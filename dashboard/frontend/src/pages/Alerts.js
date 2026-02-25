import React, { useState, useEffect } from 'react';
import { AlertTriangle, AlertCircle, Info, X } from 'lucide-react';
import '../styles/Alerts.css';
import apiClient from '../api/client';

function Alerts({ alerts }) {
  const [filteredAlerts, setFilteredAlerts] = useState([]);
  const [severityFilter, setSeverityFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');

  useEffect(() => {
    let filtered = alerts;

    if (severityFilter !== 'all') {
      filtered = filtered.filter(a => a.severity === severityFilter);
    }

    if (typeFilter !== 'all') {
      filtered = filtered.filter(a => a.type === typeFilter);
    }

    setFilteredAlerts(filtered);
  }, [alerts, severityFilter, typeFilter]);

  const getSeverityIcon = (severity) => {
    switch (severity) {
      case 'critical':
        return <AlertTriangle size={20} className="icon-critical" />;
      case 'high':
        return <AlertCircle size={20} className="icon-high" />;
      default:
        return <Info size={20} className="icon-info" />;
    }
  };

  const getTypeLabel = (type) => {
    return type.charAt(0).toUpperCase() + type.slice(1);
  };

  return (
    <div className="alerts-page">
      <div className="page-header">
        <h2>System Alerts</h2>
        <p>Monitor and manage system alerts and anomalies</p>
      </div>

      {/* Filters */}
      <div className="alerts-filters">
        <div className="filter-group">
          <label>Severity:</label>
          <select 
            value={severityFilter} 
            onChange={(e) => setSeverityFilter(e.target.value)}
          >
            <option value="all">All Severities</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </div>

        <div className="filter-group">
          <label>Type:</label>
          <select 
            value={typeFilter} 
            onChange={(e) => setTypeFilter(e.target.value)}
          >
            <option value="all">All Types</option>
            <option value="anomaly">Anomaly</option>
            <option value="trash">Trash Detection</option>
            <option value="system">System</option>
          </select>
        </div>

        <div className="filter-stats">
          <span className="stat">Total: {alerts.length}</span>
          <span className="stat">Filtered: {filteredAlerts.length}</span>
        </div>
      </div>

      {/* Alerts List */}
      <div className="alerts-list">
        {filteredAlerts.length > 0 ? (
          filteredAlerts.map((alert, index) => (
            <div key={index} className={`alert-item ${alert.severity}`}>
              <div className="alert-icon">
                {getSeverityIcon(alert.severity)}
              </div>

              <div className="alert-content">
                <div className="alert-title">
                  <h4>{alert.message}</h4>
                  <span className="alert-type">{getTypeLabel(alert.type)}</span>
                </div>

                <div className="alert-details">
                  <span className="detail-item">
                    <strong>Node:</strong> {alert.node_id || 'System'}
                  </span>
                  <span className="detail-item">
                    <strong>Time:</strong> {new Date(alert.timestamp).toLocaleString()}
                  </span>
                  <span className={`severity-badge ${alert.severity}`}>
                    {alert.severity.toUpperCase()}
                  </span>
                </div>
              </div>

              <button className="alert-close" title="Dismiss">
                <X size={18} />
              </button>
            </div>
          ))
        ) : (
          <div className="no-alerts">
            <div className="no-alerts-icon">✓</div>
            <h3>No Alerts</h3>
            <p>
              {(severityFilter !== 'all' || typeFilter !== 'all')
                ? 'No alerts match the selected filters' 
                : 'All systems operating normally'}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

export default Alerts;
