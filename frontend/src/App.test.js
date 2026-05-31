import { act, render, screen } from '@testing-library/react';
import App from './App';

jest.mock('./components/Status', () => () => <div>Status Mock</div>);
jest.mock('./components/SettingsPage', () => () => <div>Settings Page Mock</div>);
jest.mock('./components/LivePage', () => () => <div>Live Page Mock</div>);
jest.mock('./components/ModelLogsPage', () => () => <div>Model Logs Mock</div>);
jest.mock('./components/ApiDocsPage', () => () => <div>API Docs Mock</div>);
jest.mock('./components/IncidentPage', () => () => <div>Triggers Mock</div>);
jest.mock('./components/Incident', () => () => <div>Trigger Mock</div>);

beforeEach(() => {
  global.fetch = jest.fn(() =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ theme_key: 'fidelity-light' }),
    })
  );
});

afterEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
});

describe('App routing shell', () => {
  test('redirects root to settings monitoring tab and renders updated nav order', async () => {
    window.history.pushState({}, '', '/');

    await act(async () => {
      render(<App />);
    });

    expect((await screen.findAllByText('Settings Page Mock')).length).toBeGreaterThan(0);
    expect(window.location.pathname).toBe('/settings');
    expect(window.location.search).toBe('?tab=monitoring');

    const navLinks = screen.getAllByRole('link').map((link) => link.textContent);
    expect(navLinks).toEqual([
      'Triggers',
      'Rules',
      'Model Logs',
      'Connectors',
      'Live',
      'Settings',
      'API Docs',
    ]);
    expect(screen.getByText('Hearthlight')).toBeTruthy();
    expect(screen.getByAltText('Hearthlight logo')).toBeTruthy();
    expect(screen.queryByLabelText('Theme')).toBeNull();
    expect(screen.getByText('Live Page Mock')).toBeTruthy();
    expect(screen.getByText('Model Logs Mock')).toBeTruthy();
    expect(screen.getByText('API Docs Mock')).toBeTruthy();
    expect(screen.getByText('Triggers Mock')).toBeTruthy();
  });

  test('redirects monitoring route into settings monitoring tab', async () => {
    window.history.pushState({}, '', '/monitoring');

    await act(async () => {
      render(<App />);
    });

    expect((await screen.findAllByText('Settings Page Mock')).length).toBeGreaterThan(0);
    expect(window.location.pathname).toBe('/settings');
    expect(window.location.search).toBe('?tab=monitoring');
  });

  test('routes standalone rules page outside the settings tab list', async () => {
    window.history.pushState({}, '', '/rules');

    await act(async () => {
      render(<App />);
    });

    expect((await screen.findAllByText('Settings Page Mock')).length).toBeGreaterThan(0);
    expect(window.location.pathname).toBe('/rules');
  });

  test('redirects legacy poi route into settings sources tab', async () => {
    window.history.pushState({}, '', '/poi');

    await act(async () => {
      render(<App />);
    });

    expect((await screen.findAllByText('Settings Page Mock')).length).toBeGreaterThan(0);
    expect(window.location.pathname).toBe('/settings');
    expect(window.location.search).toBe('?tab=sources');
  });

  test('redirects legacy entity route into standalone rules page', async () => {
    window.history.pushState({}, '', '/entities');

    await act(async () => {
      render(<App />);
    });

    expect((await screen.findAllByText('Settings Page Mock')).length).toBeGreaterThan(0);
    expect(window.location.pathname).toBe('/rules');
  });
});
