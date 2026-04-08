import React from 'react';
import { Menu, AlertCircle, Wifi, WifiOff, RefreshCw } from 'lucide-react';
import '../styles/Header.css';

function Header({ isConnected, onSidebarToggle }) {
  const currentTime = new Date().toLocaleString();

  return (
    <header className="header">
      <div className="header-left">
        <button className="sidebar-toggle" onClick={onSidebarToggle}>
          <Menu size={24} />
        </button>
        <h1>River Monitoring System</h1>
      </div>
      
      <div className="header-right">
        <div className="header-info">
          <span className="current-time">{currentTime}</span>
          <div className={`connection-status ${isConnected ? 'connected' : 'disconnected'}`}>
            {isConnected ? (
              <>
                <Wifi size={16} />
                <span>Connected</span>
              </>
            ) : (
              <>
                <WifiOff size={16} />
                <span>Offline</span>
              </>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}

export default Header;
