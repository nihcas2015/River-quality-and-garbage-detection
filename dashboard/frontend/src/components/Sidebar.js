import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { 
  LayoutDashboard, 
  Network, 
  Trash2, 
  AlertTriangle, 
  Settings,
  ChevronRight
} from 'lucide-react';
import '../styles/Sidebar.css';

function Sidebar({ isOpen, onToggle }) {
  const location = useLocation();

  const menuItems = [
    { path: '/', label: 'Dashboard', icon: LayoutDashboard },
    { path: '/nodes', label: 'Node Status', icon: Network },
    { path: '/trash', label: 'Trash Analytics', icon: Trash2 },
    { path: '/alerts', label: 'Alerts', icon: AlertTriangle },
    { path: '/settings', label: 'Settings', icon: Settings },
  ];

  return (
    <aside className={`sidebar ${isOpen ? 'open' : 'closed'}`}>
      <div className="sidebar-header">
        <h2>Navigation</h2>
      </div>
      
      <nav className="sidebar-nav">
        {menuItems.map((item) => (
          <Link 
            key={item.path} 
            to={item.path}
            className={`nav-link ${location.pathname === item.path ? 'active' : ''}`}
            title={item.label}
          >
            <item.icon size={20} />
            <span className="nav-label">{item.label}</span>
            {location.pathname === item.path && <ChevronRight size={16} />}
          </Link>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className="system-info">
          <p className="info-label">System Status</p>
          <div className="status-badge active">Active</div>
        </div>
      </div>
    </aside>
  );
}

export default Sidebar;
