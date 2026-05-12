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
            Triggers
          </NavLink>
          <NavLink
            to="/rules"
            className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
          >
            Rules
          </NavLink>
          <NavLink
            to="/connectors"
            className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
          >
            Connectors
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
            <Route
              path="/rules"
              element={(
                <SettingsPage
                  forcedTab="rules"
                  hideTabBar
                  pageTitle="Rules"
                  pageSubtitle="Define detector and anomaly trigger rules without mixing them into the main settings tabs."
                />
              )}
            />
            <Route
              path="/connectors"
              element={(
                <SettingsPage
                  forcedTab="connectors"
                  hideTabBar
                  pageTitle="Connectors"
                  pageSubtitle="Manage outbound trigger delivery channels separately from core workspace settings."
                />
              )}
            />
            <Route path="/monitoring" element={<Navigate to="/settings?tab=monitoring" replace />} />
            <Route path="/live" element={<LivePage />} />
            <Route path="/api-docs" element={<ApiDocsPage />} />
            <Route path="/incidents" element={<IncidentPage />} />
            <Route path="/incident/:incidentId" element={<Incident />} />
            <Route path="/entities" element={<Navigate to="/rules" replace />} />
            <Route path="/entity/:entityId" element={<Navigate to="/rules" replace />} />
            <Route path="/poi" element={<Navigate to="/settings?tab=sources" replace />} />
            <Route path="/poi/:poiId" element={<Navigate to="/settings?tab=sources" replace />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
};
export default App;
