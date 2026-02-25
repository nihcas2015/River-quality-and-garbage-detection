import React, { useState, useEffect, useCallback } from 'react';
import {
  BarChart, Bar, LineChart, Line, AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, PieChart, Pie, Cell, RadialBarChart, RadialBar
} from 'recharts';
import { Thermometer, Droplet, AlertTriangle, Trash2, Activity, Waves } from 'lucide-react';
import MetricCard from '../components/MetricCard';
import ChartContainer from '../components/ChartContainer';
import '../styles/Dashboard.css';

const COLORS = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#3b82f6', '#8b5cf6'];

/* ── Water Quality Index (0–100) ── */
function computeWQI(temp, ph) {
  let tScore = 100;
  if (temp < 4 || temp > 35) tScore = 20;
  else if (temp < 10 || temp > 28) tScore = 60;
  else tScore = 100;

  let pScore = 100;
  if (ph < 6 || ph > 9) pScore = 20;
  else if (ph < 6.5 || ph > 8.5) pScore = 60;
  else pScore = 100;

  return Math.round((tScore * 0.5 + pScore * 0.5));
}

function getWQILabel(wqi) {
  if (wqi >= 80) return { text: 'Good', color: '#22c55e' };
  if (wqi >= 50) return { text: 'Moderate', color: '#f59e0b' };
  return { text: 'Poor', color: '#ef4444' };
}

/* ── Custom Tooltip ── */
const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      <p className="tooltip-label">{label}</p>
      {payload.map((entry, i) => (
        <p key={i} style={{ color: entry.color }}>
          {entry.name}: <strong>{typeof entry.value === 'number' ? entry.value.toFixed(2) : entry.value}</strong>
        </p>
      ))}
    </div>
  );
};

function Dashboard({ riverData, federationStatus, latestReadings, alerts }) {
  const [chartData, setChartData] = useState([]);
  const [nodeMetrics, setNodeMetrics] = useState([]);

  /* keep a rolling history of readings (max 30 points) */
  const [timeHistory, setTimeHistory] = useState([]);

  const appendHistory = useCallback((temp, ph) => {
    setTimeHistory(prev => {
      const now = new Date();
      const point = {
        time: now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        temperature: parseFloat(temp?.toFixed(2)) || 0,
        ph: parseFloat(ph?.toFixed(2)) || 7,
      };
      const next = [...prev, point];
      return next.length > 30 ? next.slice(-30) : next;
    });
  }, []);

  useEffect(() => {
    if (riverData) {
      appendHistory(riverData.avg_temperature, riverData.avg_ph);

      /* If history is empty, seed 6 initial points */
      if (timeHistory.length === 0) {
        const now = new Date();
        const seed = [];
        for (let i = 5; i >= 0; i--) {
          const t = new Date(now - i * 60000);
          seed.push({
            time: t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
            temperature: parseFloat(((riverData.avg_temperature || 22) + Math.random() * 2 - 1).toFixed(2)),
            ph: parseFloat(((riverData.avg_ph || 7) + Math.random() * 0.5 - 0.25).toFixed(2)),
          });
        }
        setTimeHistory(seed);
      }
    }

    if (latestReadings) {
      const metrics = Object.entries(latestReadings).map(([nodeId, data]) => ({
        node_id: nodeId.replace('pi4_', ''),
        temperature: data.sensor_data?.temperature || 0,
        ph: data.sensor_data?.ph || 7,
        trash_count: data.detection_result?.trash_count || 0,
      }));
      setNodeMetrics(metrics);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [riverData, latestReadings]);

  /* ── derived values ── */
  const avgTemp = riverData?.avg_temperature || 0;
  const avgPh  = riverData?.avg_ph || 7;
  const wqi = computeWQI(avgTemp, avgPh);
  const wqiInfo = getWQILabel(wqi);

  const getTemperatureStatus = () => {
    if (avgTemp < 4 || avgTemp > 35) return 'critical';
    if (avgTemp < 10 || avgTemp > 28) return 'warning';
    return 'normal';
  };

  const getPhStatus = () => {
    if (avgPh < 6 || avgPh > 9) return 'critical';
    if (avgPh < 6.5 || avgPh > 8.5) return 'warning';
    return 'normal';
  };

  const anomalyCounts = riverData?.anomalies || {};
  const totalAnomalies = Object.values(anomalyCounts).reduce((a, b) => a + b, 0);
  const totalTrash = riverData?.total_trash_detected || 0;

  const anomalyPieData = [
    { name: 'Temperature', value: anomalyCounts.temperature || 0 },
    { name: 'pH Level', value: anomalyCounts.ph || 0 },
    { name: 'Trash', value: totalTrash },
  ].filter(item => item.value > 0);

  const wqiGaugeData = [{ name: 'WQI', value: wqi, fill: wqiInfo.color }];

  const displayHistory = timeHistory.length > 0 ? timeHistory : chartData;

  return (
    <div className="dashboard">
      {/* Header */}
      <div className="dashboard-header">
        <div>
          <h2>River Monitoring Dashboard</h2>
          <p className="last-update">
            Live updates every 5 seconds &middot; Last refresh: {new Date().toLocaleTimeString()}
          </p>
        </div>
        <div className="connection-badge">
          <span className={`pulse ${federationStatus?.active_nodes > 0 ? 'active' : ''}`}></span>
          {federationStatus?.active_nodes || 0} node{(federationStatus?.active_nodes || 0) !== 1 ? 's' : ''} online
        </div>
      </div>

      {/* ── Key Metrics ── */}
      <div className="metrics-grid">
        <MetricCard
          title="Water Temperature"
          value={avgTemp ? avgTemp.toFixed(1) : '--'}
          unit="°C"
          icon={Thermometer}
          status={getTemperatureStatus()}
        />
        <MetricCard
          title="pH Level"
          value={avgPh ? avgPh.toFixed(2) : '--'}
          unit=""
          icon={Droplet}
          status={getPhStatus()}
        />
        <MetricCard
          title="Water Quality"
          value={wqi}
          unit={`/ 100 — ${wqiInfo.text}`}
          icon={Waves}
          status={wqi >= 80 ? 'normal' : wqi >= 50 ? 'warning' : 'critical'}
        />
        <MetricCard
          title="Trash Detected"
          value={totalTrash}
          unit="items"
          icon={Trash2}
          status={totalTrash > 5 ? 'warning' : 'normal'}
        />
      </div>

      {/* ── Status Bar ── */}
      <div className="status-overview">
        <div className="status-item">
          <span className="status-label">Active Nodes</span>
          <span className="status-value">
            {federationStatus?.active_nodes || 0}<span className="status-total">/{federationStatus?.total_nodes || 0}</span>
          </span>
        </div>
        <div className="status-item">
          <span className="status-label">Fed. Round</span>
          <span className="status-value">{federationStatus?.global_round || 0}</span>
        </div>
        <div className="status-item">
          <span className="status-label">Anomalies</span>
          <span className="status-value anomaly-count">{totalAnomalies}</span>
        </div>
        <div className="status-item">
          <span className="status-label">Alerts</span>
          <span className="status-value alert-count">{alerts.length}</span>
        </div>
      </div>

      {/* ── Charts Row 1: Sensor Trends + Water Quality Gauge ── */}
      <div className="charts-row">
        <ChartContainer title="Temperature & pH — Live Trend" className="chart-wide">
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={displayHistory}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="time" tick={{ fontSize: 11 }} />
              <YAxis yAxisId="left" tick={{ fontSize: 11 }} domain={['auto', 'auto']} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} domain={['auto', 'auto']} />
              <Tooltip content={<CustomTooltip />} />
              <Legend />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="temperature"
                stroke="#ef4444"
                name="Temperature (°C)"
                strokeWidth={2}
                dot={false}
                animationDuration={500}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="ph"
                stroke="#3b82f6"
                name="pH Level"
                strokeWidth={2}
                dot={false}
                animationDuration={500}
              />
            </LineChart>
          </ResponsiveContainer>
        </ChartContainer>

        <ChartContainer title="Water Quality Index">
          <div className="wqi-gauge-wrapper">
            <ResponsiveContainer width="100%" height={220}>
              <RadialBarChart
                innerRadius="70%"
                outerRadius="100%"
                data={wqiGaugeData}
                startAngle={180}
                endAngle={0}
                barSize={18}
              >
                <RadialBar background clockWise dataKey="value" cornerRadius={10} />
              </RadialBarChart>
            </ResponsiveContainer>
            <div className="wqi-center">
              <span className="wqi-number" style={{ color: wqiInfo.color }}>{wqi}</span>
              <span className="wqi-label">{wqiInfo.text}</span>
            </div>
          </div>
          {anomalyPieData.length > 0 && (
            <ResponsiveContainer width="100%" height={140}>
              <PieChart>
                <Pie
                  data={anomalyPieData}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, value }) => `${name}: ${value}`}
                  outerRadius={55}
                  innerRadius={30}
                  fill="#8884d8"
                  dataKey="value"
                  paddingAngle={3}
                >
                  {anomalyPieData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          )}
        </ChartContainer>
      </div>

      {/* ── Charts Row 2: Node Comparison + Trash Timeline ── */}
      <div className="charts-row">
        <ChartContainer title="Per-Node Comparison">
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={nodeMetrics.slice(0, 10)} barGap={4}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="node_id" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip content={<CustomTooltip />} />
              <Legend />
              <Bar dataKey="temperature" fill="#ef4444" name="Temp (°C)" radius={[4, 4, 0, 0]} />
              <Bar dataKey="ph" fill="#3b82f6" name="pH" radius={[4, 4, 0, 0]} />
              <Bar dataKey="trash_count" fill="#8b5cf6" name="Trash" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartContainer>

        <ChartContainer title="Temperature Trend (Area)">
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={displayHistory}>
              <defs>
                <linearGradient id="tempGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="time" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} domain={['auto', 'auto']} />
              <Tooltip content={<CustomTooltip />} />
              <Area
                type="monotone"
                dataKey="temperature"
                stroke="#ef4444"
                fill="url(#tempGrad)"
                strokeWidth={2}
                name="Temperature (°C)"
                animationDuration={500}
              />
            </AreaChart>
          </ResponsiveContainer>
        </ChartContainer>
      </div>

      {/* ── Recent Alerts ── */}
      <div className="recent-alerts">
        <div className="section-header">
          <h3><AlertTriangle size={18} /> Recent Alerts</h3>
          <span className="badge">{alerts.length}</span>
        </div>
        <div className="alerts-list">
          {alerts.length > 0 ? (
            alerts.slice(0, 5).map((alert, index) => (
              <div key={index} className={`alert-item ${alert.severity}`}>
                <AlertTriangle size={16} />
                <div className="alert-content">
                  <p className="alert-message">{alert.message}</p>
                  <span className="alert-node">{alert.node_id}</span>
                </div>
                <span className="alert-time">
                  {new Date(alert.timestamp).toLocaleTimeString()}
                </span>
              </div>
            ))
          ) : (
            <p className="no-alerts-text">All systems operating normally.</p>
          )}
        </div>
      </div>
    </div>
  );
}

export default Dashboard;
