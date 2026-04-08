import React, { useState, useEffect } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, PieChart, Pie, Cell,
} from 'recharts';
import { Trash2, Package, Layers, TrendingUp } from 'lucide-react';
import ChartContainer from '../components/ChartContainer';
import '../styles/TrashAnalytics.css';
import apiClient from '../api/client';

const CLASS_COLORS = {
  Plastic:  '#ef4444',
  Paper:    '#f97316',
  Metal:    '#6366f1',
  Glass:    '#3b82f6',
  Organic:  '#22c55e',
  Textile:  '#8b5cf6',
};
const FALLBACK_COLORS = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#3b82f6', '#8b5cf6', '#ec4899'];

function TrashAnalytics() {
  const [trashHistory, setTrashHistory] = useState([]);
  const [classTotals, setClassTotals] = useState({});
  const [loading, setLoading] = useState(false);
  const [timeRange, setTimeRange] = useState(24);
  const [stats, setStats] = useState({ total: 0, average: 0, peak: 0 });

  useEffect(() => {
    fetchTrashData();
  }, [timeRange]);

  const fetchTrashData = async () => {
    try {
      setLoading(true);
      const response = await apiClient.get('/dashboard/trash_history', {
        params: { hours: timeRange, limit: 200 },
      });

      const data = response.data.trash_events || [];
      setTrashHistory(data);
      setClassTotals(response.data.class_totals || {});

      const totalTrash = response.data.total_count || 0;
      const average = data.length > 0 ? (totalTrash / data.length).toFixed(2) : 0;
      const peak = data.length > 0 ? Math.max(...data.map(t => t.count)) : 0;
      setStats({ total: totalTrash, average, peak });
    } catch (error) {
      console.error('Error fetching trash data:', error);
    } finally {
      setLoading(false);
    }
  };

  /* ── Derived chart data ── */

  // Class distribution pie
  const classData = Object.entries(classTotals).map(([name, value]) => ({ name, value }));
  const getClassColor = (name, idx) => CLASS_COLORS[name] || FALLBACK_COLORS[idx % FALLBACK_COLORS.length];

  // Timeline (hourly buckets with per-class stacking)
  const timelineData = [];
  const currentTime = new Date();
  for (let i = 0; i < 12; i++) {
    const timeSlot = new Date(currentTime - i * 60 * 60 * 1000);
    const timeLabel = timeSlot.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const matchingEvents = trashHistory.filter(t => {
      const eventTime = new Date(t.timestamp);
      return eventTime.getHours() === timeSlot.getHours();
    });
    const count = matchingEvents.reduce((sum, t) => sum + t.count, 0);
    const slotClasses = {};
    matchingEvents.forEach(t => {
      Object.entries(t.class_counts || {}).forEach(([cls, cnt]) => {
        slotClasses[cls] = (slotClasses[cls] || 0) + cnt;
      });
    });
    timelineData.unshift({ time: timeLabel, count, ...slotClasses });
  }

  // Per-class bar chart
  const classBarData = Object.entries(classTotals)
    .sort((a, b) => b[1] - a[1])
    .map(([name, count]) => ({ name, count }));

  // Node distribution
  const nodeDistribution = {};
  trashHistory.forEach(event => {
    if (!nodeDistribution[event.node_id]) nodeDistribution[event.node_id] = 0;
    nodeDistribution[event.node_id] += event.count;
  });
  const nodeData = Object.entries(nodeDistribution).map(([nodeId, count]) => ({
    name: nodeId, trash_count: count,
  }));

  // All unique classes for stacked bars
  const allClasses = [...new Set(
    trashHistory.flatMap(t => Object.keys(t.class_counts || {}))
  )];

  return (
    <div className="trash-analytics">
      <div className="page-header">
        <h2><Trash2 size={24} /> Trash Detection Analytics</h2>
        <p>Real-time monitoring — YOLO class-level breakdown from river-trash model</p>
      </div>

      {/* Statistics Cards */}
      <div className="stats-cards">
        <div className="stat-card">
          <div className="stat-icon"><Trash2 size={28} color="#ef4444" /></div>
          <div className="stat-info">
            <h3>Total Detected</h3>
            <p className="stat-value">{stats.total}</p>
            <p className="stat-period">Last {timeRange} hours</p>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon"><TrendingUp size={28} color="#3b82f6" /></div>
          <div className="stat-info">
            <h3>Avg Per Detection</h3>
            <p className="stat-value">{stats.average}</p>
            <p className="stat-period">items/event</p>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon"><Layers size={28} color="#8b5cf6" /></div>
          <div className="stat-info">
            <h3>Classes Found</h3>
            <p className="stat-value">{Object.keys(classTotals).length}</p>
            <p className="stat-period">unique types</p>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon"><Package size={28} color="#f97316" /></div>
          <div className="stat-info">
            <h3>Peak Detection</h3>
            <p className="stat-value">{stats.peak}</p>
            <p className="stat-period">single event</p>
          </div>
        </div>
      </div>

      {/* Time Range */}
      <div className="time-range-selector">
        <label>Time Range:</label>
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

      {/* Row 1: Class Pie + Class Bar */}
      <div className="charts-row">
        <ChartContainer title="Trash by Class (Overall)" loading={loading}>
          {classData.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={classData}
                  cx="50%"
                  cy="50%"
                  labelLine
                  label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                  outerRadius={100}
                  innerRadius={45}
                  fill="#8884d8"
                  dataKey="value"
                  paddingAngle={3}
                >
                  {classData.map((entry, idx) => (
                    <Cell key={`cell-${idx}`} fill={getClassColor(entry.name, idx)} />
                  ))}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="no-data-msg">No class data yet — waiting for YOLO detections</div>
          )}
        </ChartContainer>

        <ChartContainer title="Items per Class" loading={loading}>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={classBarData} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" />
              <YAxis dataKey="name" type="category" width={80} tick={{ fontSize: 12 }} />
              <Tooltip />
              <Bar dataKey="count" name="Total Items" radius={[0, 4, 4, 0]}>
                {classBarData.map((entry, idx) => (
                  <Cell key={`bar-${idx}`} fill={getClassColor(entry.name, idx)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartContainer>
      </div>

      {/* Row 2: Stacked Timeline + Node Distribution */}
      <div className="charts-row">
        <ChartContainer title="Hourly Timeline (Stacked by Class)" loading={loading}>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={timelineData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="time" />
              <YAxis />
              <Tooltip />
              <Legend />
              {allClasses.length > 0 ? (
                allClasses.map((cls, idx) => (
                  <Bar key={cls} dataKey={cls} stackId="a"
                       fill={getClassColor(cls, idx)} name={cls} />
                ))
              ) : (
                <Bar dataKey="count" fill="#ef4444" name="Trash Count" />
              )}
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
              <Bar dataKey="trash_count" fill="#f97316" name="Detected Items" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartContainer>
      </div>

      {/* Recent Detections with Class Breakdown */}
      <div className="recent-detections">
        <h3>Recent Detections</h3>
        <div className="detections-table">
          <table>
            <thead>
              <tr>
                <th>Node ID</th>
                <th>Total</th>
                <th>Class Breakdown</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {trashHistory.slice(-20).reverse().map((event, index) => (
                <tr key={index}>
                  <td className="node-cell">{event.node_id}</td>
                  <td className="count-cell">
                    <span className="count-badge">{event.count}</span>
                  </td>
                  <td className="class-cell">
                    {event.class_counts && Object.keys(event.class_counts).length > 0 ? (
                      <div className="class-tags">
                        {Object.entries(event.class_counts).map(([cls, cnt]) => (
                          <span
                            key={cls}
                            className="class-tag"
                            style={{
                              backgroundColor: getClassColor(cls, 0) + '22',
                              color: getClassColor(cls, 0),
                              border: `1px solid ${getClassColor(cls, 0)}40`,
                            }}
                          >
                            {cls}: {cnt}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="no-class">—</span>
                    )}
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
