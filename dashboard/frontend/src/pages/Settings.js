import React, { useState } from 'react';
import { Save, RotateCcw } from 'lucide-react';
import '../styles/Settings.css';

function Settings() {
  const [settings, setSettings] = useState({
    updateInterval: 5,
    tempThreshold: { min: 4, max: 35 },
    phThreshold: { min: 6, max: 9 },
    trashAlertThreshold: 5,
    enableNotifications: true,
    alertSeverity: 'high',
  });

  const [savedMessage, setSavedMessage] = useState(null);

  const handleSave = () => {
    localStorage.setItem('dashboardSettings', JSON.stringify(settings));
    setSavedMessage('Settings saved successfully!');
    setTimeout(() => setSavedMessage(null), 3000);
  };

  const handleReset = () => {
    if (window.confirm('Reset all settings to defaults?')) {
      setSettings({
        updateInterval: 5,
        tempThreshold: { min: 4, max: 35 },
        phThreshold: { min: 6, max: 9 },
        trashAlertThreshold: 5,
        enableNotifications: true,
        alertSeverity: 'high',
      });
    }
  };

  const handleChange = (key, value) => {
    setSettings(prev => ({ ...prev, [key]: value }));
  };

  const handleThresholdChange = (threshold, bound, value) => {
    setSettings(prev => ({
      ...prev,
      [threshold]: { ...prev[threshold], [bound]: parseFloat(value) },
    }));
  };

  return (
    <div className="settings-page">
      <div className="page-header">
        <h2>Dashboard Settings</h2>
        <p>Configure monitoring thresholds and preferences</p>
      </div>

      {savedMessage && <div className="success-message">✓ {savedMessage}</div>}

      <div className="settings-container">
        {/* General */}
        <section className="settings-section">
          <h3>General</h3>
          <div className="setting-item">
            <label htmlFor="updateInterval">Update Interval (seconds)</label>
            <input id="updateInterval" type="number" min="1" max="60"
              value={settings.updateInterval}
              onChange={(e) => handleChange('updateInterval', parseInt(e.target.value))} />
          </div>
          <div className="setting-item">
            <label htmlFor="enableNotifications">
              <input id="enableNotifications" type="checkbox"
                checked={settings.enableNotifications}
                onChange={(e) => handleChange('enableNotifications', e.target.checked)} />
              Enable Notifications
            </label>
          </div>
          <div className="setting-item">
            <label htmlFor="alertSeverity">Minimum Alert Severity</label>
            <select id="alertSeverity" value={settings.alertSeverity}
              onChange={(e) => handleChange('alertSeverity', e.target.value)}>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>
          </div>
        </section>

        {/* Temperature */}
        <section className="settings-section">
          <h3>Temperature Thresholds</h3>
          <div className="threshold-group">
            <div className="threshold-item">
              <label htmlFor="tempMin">Min (°C)</label>
              <input id="tempMin" type="number"
                value={settings.tempThreshold.min}
                onChange={(e) => handleThresholdChange('tempThreshold', 'min', e.target.value)} />
            </div>
            <div className="threshold-item">
              <label htmlFor="tempMax">Max (°C)</label>
              <input id="tempMax" type="number"
                value={settings.tempThreshold.max}
                onChange={(e) => handleThresholdChange('tempThreshold', 'max', e.target.value)} />
            </div>
          </div>
        </section>

        {/* pH */}
        <section className="settings-section">
          <h3>pH Level Thresholds</h3>
          <div className="threshold-group">
            <div className="threshold-item">
              <label htmlFor="phMin">Min pH</label>
              <input id="phMin" type="number" step="0.1"
                value={settings.phThreshold.min}
                onChange={(e) => handleThresholdChange('phThreshold', 'min', e.target.value)} />
            </div>
            <div className="threshold-item">
              <label htmlFor="phMax">Max pH</label>
              <input id="phMax" type="number" step="0.1"
                value={settings.phThreshold.max}
                onChange={(e) => handleThresholdChange('phThreshold', 'max', e.target.value)} />
            </div>
          </div>
        </section>

        {/* Trash */}
        <section className="settings-section">
          <h3>Trash Detection</h3>
          <div className="setting-item">
            <label htmlFor="trashThreshold">Alert when trash count exceeds</label>
            <input id="trashThreshold" type="number" min="1"
              value={settings.trashAlertThreshold}
              onChange={(e) => handleChange('trashAlertThreshold', parseInt(e.target.value))} />
          </div>
        </section>

        {/* System Info */}
        <section className="settings-section info-section">
          <h3>System Information</h3>
          <div className="info-grid">
            <div className="info-item">
              <span className="info-label">Dashboard Version</span>
              <span className="info-value">1.0.0</span>
            </div>
            <div className="info-item">
              <span className="info-label">Last Updated</span>
              <span className="info-value">{new Date().toLocaleDateString()}</span>
            </div>
          </div>
        </section>
      </div>

      <div className="settings-actions">
        <button className="btn btn-primary" onClick={handleSave}>
          <Save size={18} /> Save Settings
        </button>
        <button className="btn btn-secondary" onClick={handleReset}>
          <RotateCcw size={18} /> Reset to Defaults
        </button>
      </div>
    </div>
  );
}

export default Settings;
