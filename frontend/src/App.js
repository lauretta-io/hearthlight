import React, { useEffect, useState } from 'react';
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
import ModelLogsPage from './components/ModelLogsPage';
import SettingsPage from './components/SettingsPage';
import ApiDocsPage from './components/ApiDocsPage';
import LivePage from './components/LivePage';
import { BaseURL } from './config';
import { DEFAULT_THEME, getThemeOption, THEME_OPTIONS, THEME_STORAGE_KEY } from './theme';
import './styles/App.css';
const App = () => {
  const [theme, setTheme] = useState(() => window.localStorage.getItem(THEME_STORAGE_KEY) || DEFAULT_THEME);
  const [appearanceLoaded, setAppearanceLoaded] = useState(false);
  const [appearanceError, setAppearanceError] = useState('');
  const [isSavingAppearance, setIsSavingAppearance] = useState(false);

  useEffect(() => {
    const option = getThemeOption(theme);
    document.documentElement.dataset.theme = option.key;
    document.documentElement.style.colorScheme = option.colorScheme;
    window.localStorage.setItem(THEME_STORAGE_KEY, option.key);
  }, [theme]);

  useEffect(() => {
    let cancelled = false;
    const loadAppearance = async () => {
      try {
        const response = await fetch(`${BaseURL}/settings/appearance`);
        if (!response.ok) {
          let detail = 'Failed to load appearance settings.';
          try {
            const payload = await response.json();
            detail = payload?.detail || detail;
          } catch (error) {
            // Keep the fallback detail when the response is not JSON.
          }
          throw new Error(detail);
        }
        const payload = await response.json();
        const nextTheme = getThemeOption(payload?.theme_key).key;
        if (!cancelled) {
          setTheme(nextTheme);
          setAppearanceError('');
        }
      } catch (error) {
        if (!cancelled) {
          setAppearanceError(error.message || 'Failed to load appearance settings.');
        }
      } finally {
        if (!cancelled) {
          setAppearanceLoaded(true);
        }
      }
    };
    loadAppearance();
    return () => {
      cancelled = true;
    };
  }, []);

  const saveAppearance = async (themeKey) => {
    const normalizedTheme = getThemeOption(themeKey).key;
    setIsSavingAppearance(true);
    try {
      const response = await fetch(`${BaseURL}/settings/appearance`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ theme_key: normalizedTheme }),
      });
      if (!response.ok) {
        let detail = 'Failed to save appearance settings.';
        try {
          const payload = await response.json();
          detail = payload?.detail || detail;
        } catch (error) {
          // Keep fallback detail.
        }
        throw new Error(detail);
      }
      const payload = await response.json();
      const persistedTheme = getThemeOption(payload?.theme_key).key;
      setTheme(persistedTheme);
      setAppearanceError('');
      return persistedTheme;
    } catch (error) {
      setAppearanceError(error.message || 'Failed to save appearance settings.');
      throw error;
    } finally {
      setIsSavingAppearance(false);
    }
  };

  const settingsSharedProps = {
    themeOptions: THEME_OPTIONS,
    currentThemeKey: theme,
    appearanceLoaded,
    appearanceError,
    isSavingAppearance,
    onSaveAppearance: saveAppearance,
  };

  return (
    <Router>
      <div className="app">
        <nav className="top-nav">
          <div className="brand-block">
            <div className="brand-mark">Hearthlight</div>
            <div className="brand-submark">{getThemeOption(theme).label}</div>
          </div>
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
            to="/model-logs"
            className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}
          >
            Model Logs
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
            <Route path="/" element={<Navigate to="/settings?tab=monitoring" replace />} />
            <Route path="/settings" element={<SettingsPage {...settingsSharedProps} />} />
            <Route
              path="/rules"
              element={(
                <SettingsPage
                  {...settingsSharedProps}
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
                  {...settingsSharedProps}
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
            <Route path="/model-logs" element={<ModelLogsPage />} />
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
