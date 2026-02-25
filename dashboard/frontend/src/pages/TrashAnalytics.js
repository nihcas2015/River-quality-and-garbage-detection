import React, { useState, useEffect } from 'react';
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import ChartContainer from '../components/ChartContainer';
import '../styles/TrashAnalytics.css';
import apiClient from '../api/client';

const COLORS = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#3b82f6'];

function TrashAnalytics() {
  const [trashHistory, setTrashHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [timeRange, setTimeRange] = useState(24);
  const [stats, setStats] = useState({
    total: 0,
    average: 0,
    peak: 0,
  });

  useEffect(() => {
    fetchTrashData();
  }, [timeRange]);

  const fetchTrashData = async () => {
    try {
      setLoading(true);
      const response = await apiClient.get('/dashboard/trash_history', {
        params: { hours: timeRange, limit: 100 },
      });
      
      const data = response.data.trash_events || [];
      setTrashHistory(data);

      // Calculate statistics
      const totalTrash = response.data.total_count || 0;
      const average = data.length > 0 ? (totalTrash / data.length).toFixed(2) : 0;
      const peak = data.length > 0 ? Math.max(...data.map(t => t.count)) : 0;

      setStats({
        total: totalTrash,
        average,
        peak,
      });
    } catch (error) {
      console.error('Error fetching trash data:', error);
    } finally {
      setLoading(false);
    }
  };

  // Process data for timeline chart
  const timelineData = [];
  let currentTime = new Date();
  
  for (let i = 0; i < 12; i++) {
    const timeSlot = new Date(currentTime - i * 60 * 60 * 1000);
    const timeLabel = timeSlot.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const count = trashHistory
      .filter(t => {
        const eventTime = new Date(t.timestamp);
        return eventTime.getHours() === timeSlot.getHours();
      })
      .reduce((sum, t) => sum + t.count, 0);
    
    timelineData.unshift({ time: timeLabel, count });
  }

  // Process data for node distribution
  const nodeDistribution = {};
  trashHistory.forEach(event => {
    if (!nodeDistribution[event.node_id]) {
      nodeDistribution[event.node_id] = 0;
    }
    nodeDistribution[event.node_id] += event.count;
  });

  const nodeData = Object.entries(nodeDistribution).map(([nodeId, count]) => ({
    name: nodeId,
    trash_count: count,
  }));

  return (
    <div className="trash-analytics">
      <div className="page-header">
        <h2>Trash Detection Analytics</h2>
        <p>Real-time monitoring and analysis of detected trash items</p>
      </div>

      {/* Statistics Cards */}
      <div className="stats-cards">
        <div className="stat-card">
          <div className="stat-icon">🗑️</div>
          <div className="stat-info">
            <h3>Total Trash Detected</h3>
            <p className="stat-value">{stats.total}</p>
            <p className="stat-period">Last {timeRange} hours</p>
          </div>
        </div>
        
        <div className="stat-card">
          <div className="stat-icon">📊</div>
          <div className="stat-info">
            <h3>Average Per Detection</h3>
            <p className="stat-value">{stats.average}</p>
            <p className="stat-period">items/detection</p>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon">📈</div>
          <div className="stat-info">
            <h3>Peak Detection</h3>
            <p className="stat-value">{stats.peak}</p>
            <p className="stat-period">single event</p>
          </div>
        </div>
      </div>

      {/* Time Range Selector */}
      <div className="time-range-selector">
        <label>Select Time Range:</label>
        <div className="range-buttons">
          {[6, 12, 24, 48].map((hrs) => (
            <button
              key={hrs}
              className={`range-btn ${timeRange === hrs ? 'active' : ''}`}
              onClick={() => setTimeRange(hrs)}
            >
              {hrs}h
            </button>
          ))}
        </div>
      </div>

      {/* Charts */}
      <div className="charts-row">
        <ChartContainer title="Trash Detection Timeline" loading={loading}>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={timelineData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="time" />
              <YAxis />
              <Tooltip />
              <Legend />
              <Bar dataKey="count" fill="#ef4444" name="Trash Count" />
            </BarChart>
          </ResponsiveContainer>
        </ChartContainer>

        <ChartContainer title="Trash by Node" loading={loading}>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={nodeData} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" />
              <YAxis dataKey="name" type="category" width={100} />
              <Tooltip />
              <Legend />
              <Bar dataKey="trash_count" fill="#f97316" name="Detected Items" />
            </BarChart>
          </ResponsiveContainer>
        </ChartContainer>
      </div>

      {/* Recent Detections */}
      <div className="recent-detections">
        <h3>Recent Detections</h3>
        <div className="detections-table">
          <table>
            <thead>
              <tr>
                <th>Node ID</th>
                <th>Trash Count</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {trashHistory.slice(0, 20).map((event, index) => (
                <tr key={index}>
                  <td className="node-cell">{event.node_id}</td>
                  <td className="count-cell">
                    <span className="count-badge">{event.count}</span>
                  </td>
                  <td className="time-cell">
                    {new Date(event.timestamp).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {trashHistory.length === 0 && (
            <p className="no-data">No trash detections in this period</p>
          )}
        </div>
      </div>
    </div>
  );
}

export default TrashAnalytics;
