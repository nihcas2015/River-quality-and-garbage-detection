import React, { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import io from 'socket.io-client';
import Header from './components/Header';
import Sidebar from './components/Sidebar';
import Dashboard from './pages/Dashboard';
import NodesStatus from './pages/NodesStatus';
import TrashAnalytics from './pages/TrashAnalytics';
import Alerts from './pages/Alerts';
import Settings from './pages/Settings';
import apiClient from './api/client';
import './styles/App.css';

// When hosted on Pi5, WebSocket connects to same origin
const SOCKET_URL = process.env.REACT_APP_API_URL || window.location.origin;

function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [riverData, setRiverData] = useState(null);
  const [federationStatus, setFederationStatus] = useState(null);
  const [latestReadings, setLatestReadings] = useState({});
  const [alerts, setAlerts] = useState([]);
  const [isConnected, setIsConnected] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Initialize WebSocket connection
    const socket = io(SOCKET_URL, {
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      reconnectionAttempts: 5,
    });

    socket.on('connect', () => {
      console.log('Connected to server');
      setIsConnected(true);
      socket.emit('subscribe_updates', { room: 'dashboard' });
      fetchInitialData();
    });

    socket.on('disconnect', () => {
      console.log('Disconnected from server');
      setIsConnected(false);
    });

    socket.on('dashboard_update', (data) => {
      if (data.river_data) {
        setRiverData(data.river_data);
      }
      if (data.federation_status) {
        setFederationStatus(data.federation_status);
      }
    });

    socket.on('data_update', (data) => {
      // Update latest readings
      if (data.node_id) {
        setLatestReadings((prev) => ({
          ...prev,
          [data.node_id]: {
            sensor_data: data.sensor_data,
            detection_result: data.detection_result,
            timestamp: new Date().toISOString(),
          },
        }));
      }
    });

    socket.on('alert', (data) => {
      setAlerts((prev) => [data, ...prev].slice(0, 50)); // Keep last 50 alerts
    });

    return () => {
      socket.disconnect();
    };
  }, []);

  const fetchInitialData = async () => {
    try {
      setLoading(true);
      const [riverRes, statusRes, readingsRes, alertsRes] = await Promise.all([
        apiClient.get('/dashboard/river_data'),
        apiClient.get('/federation_status'),
        apiClient.get('/dashboard/latest_readings'),
        apiClient.get('/dashboard/alerts?limit=20'),
      ]);

      setRiverData(riverRes.data);
      setFederationStatus(statusRes.data);
      setLatestReadings(readingsRes.data.readings || {});
      setAlerts(alertsRes.data.alerts || []);
    } catch (error) {
      console.error('Error fetching initial data:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Router>
      <div className="app-container">
        <Sidebar isOpen={sidebarOpen} onToggle={() => setSidebarOpen(!sidebarOpen)} />
        <div className="main-content">
          <Header 
            isConnected={isConnected} 
            onSidebarToggle={() => setSidebarOpen(!sidebarOpen)}
          />
          <div className="page-content">
            {loading ? (
              <div className="loading-container">
                <div className="spinner"></div>
                <p>Loading dashboard...</p>
              </div>
            ) : (
              <Routes>
                <Route 
                  path="/" 
                  element={
                    <Dashboard 
                      riverData={riverData} 
                      federationStatus={federationStatus}
                      latestReadings={latestReadings}
                      alerts={alerts}
                    />
                  } 
                />
                <Route 
                  path="/nodes" 
                  element={<NodesStatus federationStatus={federationStatus} />} 
                />
                <Route 
                  path="/trash" 
                  element={<TrashAnalytics />} 
                />
                <Route 
                  path="/alerts" 
                  element={<Alerts alerts={alerts} />} 
                />
                <Route 
                  path="/settings" 
                  element={<Settings />} 
                />
              </Routes>
            )}
          </div>
        </div>
      </div>
    </Router>
  );
}

export default App;
