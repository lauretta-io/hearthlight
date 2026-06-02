import React, { useEffect, useMemo, useState } from 'react';
import {
  BrowserRouter as Router,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
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

// Mount only the active page so hidden routes do not poll the API (browser
// connection limit + single-worker backend were leaving Settings requests pending).
const PersistentPage = ({ active, children }) => (
  active ? <section>{children}</section> : null
);

const AppShell = ({
  appearanceError,
  appearanceLoaded,
  currentThemeKey,
  isSavingAppearance,
  onSaveAppearance,
  themeOptions,
}) => {
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    if (location.pathname === '/') {
      navigate('/settings?tab=monitoring', { replace: true });
      return;
    }
    if (location.pathname === '/monitoring') {
      navigate('/settings?tab=monitoring', { replace: true });
      return;
    }
    if (location.pathname === '/poi') {
      navigate('/settings?tab=sources', { replace: true });
      return;
    }
    if (location.pathname.startsWith('/entity/')) {
      navigate('/rules', { replace: true });
      return;
    }
    if (location.pathname === '/entities') {
      navigate('/rules', { replace: true });
    }
  }, [location.pathname, navigate]);

  const settingsSharedProps = useMemo(
    () => ({
      themeOptions,
      currentThemeKey,
      appearanceLoaded,
      appearanceError,
      isSavingAppearance,
      onSaveAppearance,
    }),
    [
      appearanceError,
      appearanceLoaded,
      currentThemeKey,
      isSavingAppearance,
      onSaveAppearance,
      themeOptions,
    ],
  );

  const isSettingsPath = location.pathname === '/settings';
  const isRulesPath = location.pathname === '/rules';
  const isConnectorsPath = location.pathname === '/connectors';
  const isLivePath = location.pathname === '/live';
  const isApiDocsPath = location.pathname === '/api-docs';
  const isIncidentsPath = location.pathname === '/incidents';
  const isModelLogsPath = location.pathname === '/model-logs';
  const isDetailPath = location.pathname.startsWith('/incident/');

  return (
    <div className="app">
      <nav className="top-nav">
        <div className="brand-block">
          <div className="brand-logo-shell">
            <div className="brand-logo-tint" />
            <img className="brand-logo" src="/hearthlight.png" alt="Hearthlight logo" />
          </div>
          <div className="brand-copy">
            <div className="brand-mark">Hearthlight</div>
            <div className="brand-submark">{getThemeOption(currentThemeKey).label}</div>
          </div>
        </div>
        <NavLink
          to="/incidents"
          className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
        >
          Triggers
        </NavLink>
        <NavLink
          to="/rules"
          className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
        >
          Rules
        </NavLink>
        <NavLink
          to="/model-logs"
          className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
        >
          Model Logs
        </NavLink>
        <NavLink
          to="/connectors"
          className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
        >
          Connectors
        </NavLink>
        <NavLink
          to="/live"
          className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
        >
          Live
        </NavLink>
        <NavLink
          to="/settings"
          className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
        >
          Settings
        </NavLink>
        <NavLink
          to="/api-docs"
          className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
        >
          API Docs
        </NavLink>
      </nav>
      <main className="main-content">
        <Status />
        <PersistentPage active={isSettingsPath}>
          <SettingsPage {...settingsSharedProps} />
        </PersistentPage>
        <PersistentPage active={isRulesPath}>
          <SettingsPage
            {...settingsSharedProps}
            forcedTab="rules"
            hideTabBar
            pageTitle="Rules"
            pageSubtitle="Define detector and anomaly trigger rules without mixing them into the main settings tabs."
          />
        </PersistentPage>
        <PersistentPage active={isConnectorsPath}>
          <SettingsPage
            {...settingsSharedProps}
            forcedTab="connectors"
            hideTabBar
            pageTitle="Connectors"
            pageSubtitle="Manage outbound trigger delivery channels separately from core workspace settings."
          />
        </PersistentPage>
        <PersistentPage active={isLivePath}>
          <LivePage />
        </PersistentPage>
        <PersistentPage active={isApiDocsPath}>
          <ApiDocsPage />
        </PersistentPage>
        <PersistentPage active={isIncidentsPath}>
          <IncidentPage />
        </PersistentPage>
        <PersistentPage active={isModelLogsPath}>
          <ModelLogsPage />
        </PersistentPage>
        {isDetailPath && (
          <Routes>
            <Route path="/incident/:incidentId" element={<Incident />} />
          </Routes>
        )}
      </main>
    </div>
  );
};

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
          } catch (_error) {
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
        } catch (_error) {
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

  return (
    <Router>
      <AppShell
        appearanceError={appearanceError}
        appearanceLoaded={appearanceLoaded}
        currentThemeKey={theme}
        isSavingAppearance={isSavingAppearance}
        onSaveAppearance={saveAppearance}
        themeOptions={THEME_OPTIONS}
      />
    </Router>
  );
};

export default App;
