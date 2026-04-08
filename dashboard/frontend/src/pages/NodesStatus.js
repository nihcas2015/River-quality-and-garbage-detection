import React, { useState, useEffect } from 'react';
import '../styles/NodesStatus.css';

function NodesStatus({ federationStatus }) {
  const [nodeDetails, setNodeDetails] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (federationStatus?.nodes) {
      setNodeDetails(federationStatus.nodes);
    }
  }, [federationStatus]);

  const getNodeStatus = (node) => {
    const lastHeartbeat = new Date(node.last_heartbeat);
    const timeDiff = (Date.now() - lastHeartbeat.getTime()) / 1000;
    
    if (timeDiff < 30) return 'active';
    if (timeDiff < 120) return 'warning';
    return 'inactive';
  };

  const getStatusColor = (status) => {
    return status === 'active' ? '#22c55e' : status === 'warning' ? '#f59e0b' : '#ef4444';
  };

  return (
    <div className="nodes-status">
      <div className="page-header">
        <h2>Node Status Monitor</h2>
        <p>Real-time status of all edge nodes in the system</p>
      </div>

      <div className="nodes-grid">
        {nodeDetails.length > 0 ? (
          nodeDetails.map((node) => {
            const status = getNodeStatus(node);
            const timeSinceHeartbeat = Math.floor((Date.now() - new Date(node.last_heartbeat).getTime()) / 1000);
            
            return (
              <div key={node.node_id} className={`node-card ${status}`}>
                <div className="node-header">
                  <div className="node-title">
                    <h3>{node.node_id}</h3>
                    <span className="node-type">{node.node_type}</span>
                  </div>
                  <div className={`status-indicator ${status}`}></div>
                </div>

                <div className="node-details">
                  <div className="detail-item">
                    <span className="detail-label">Status</span>
                    <span className="detail-value">{status.toUpperCase()}</span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Last Heartbeat</span>
                    <span className="detail-value">{timeSinceHeartbeat}s ago</span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Rounds Participated</span>
                    <span className="detail-value">{node.rounds_participated}</span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Registered</span>
                    <span className="detail-value">
                      {new Date(node.registered_at).toLocaleDateString()}
                    </span>
                  </div>
                </div>

                <div className="node-actions">
                  {status === 'active' ? (
                    <span className="action-icon">✓</span>
                  ) : (
                    <span className="action-icon">⚠</span>
                  )}
                </div>
              </div>
            );
          })
        ) : (
          <div className="no-nodes">
            <p>No nodes registered yet</p>
          </div>
        )}
      </div>

      {/* Statistics Summary */}
      <div className="stats-summary">
        <h3>System Statistics</h3>
        <div className="stats-grid">
          <div className="stat-box">
            <div className="stat-value">{federationStatus?.active_nodes || 0}</div>
            <div className="stat-label">Active Nodes</div>
          </div>
          <div className="stat-box">
            <div className="stat-value">{federationStatus?.total_nodes || 0}</div>
            <div className="stat-label">Total Nodes</div>
          </div>
          <div className="stat-box">
            <div className="stat-value">{federationStatus?.global_round || 0}</div>
            <div className="stat-label">Federation Rounds</div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default NodesStatus;
