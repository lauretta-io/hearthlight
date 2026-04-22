import React from 'react';
import {
  BrowserRouter as Router,
  Route,
  Routes,
  NavLink,
  Navigate,
} from 'react-router-dom';
import Status from './components/Status';
import IncidentPage from './components/IncidentPage';
import Incident from './components/Incident';
import EntityPage from './components/EntityPage';
import Entity from './components/Entity';
import SettingsPage from './components/SettingsPage';
import ApiDocsPage from './components/ApiDocsPage';
import LivePage from './components/LivePage';
import './styles/App.css';
const App = () => {
  return (
    <Router>
      <div className="app">
        <nav className="top-nav">
          <NavLink
            to="/incidents"
            className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
          >
            Incidents
          </NavLink>
          <NavLink
            to="/entities"
            className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
          >
            Entities
          </NavLink>
          <NavLink
            to="/live"
            className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
          >
            Live
          </NavLink>
          <NavLink
            to="/settings"
            className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
          >
            Settings
          </NavLink>
          <NavLink
            to="/api-docs"
            className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
          >
            API Docs
          </NavLink>
        </nav>
        <main className="main-content">
          <Status />
          <Routes>
            <Route path="/" element={<Navigate to="/settings?tab=run" replace />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/monitoring" element={<Navigate to="/settings?tab=monitoring" replace />} />
            <Route path="/live" element={<LivePage />} />
            <Route path="/api-docs" element={<ApiDocsPage />} />
            <Route path="/incidents" element={<IncidentPage />} />
            <Route path="/incident/:incidentId" element={<Incident />} />
            <Route path="/entities" element={<EntityPage />} />
            <Route path="/entity/:entityId" element={<Entity />} />
            <Route path="/poi" element={<Navigate to="/settings?tab=sources" replace />} />
            <Route path="/poi/:poiId" element={<Navigate to="/settings?tab=sources" replace />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
};
export default App;
