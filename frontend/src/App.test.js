import { act, render, screen } from '@testing-library/react';
import App from './App';

jest.mock('./components/Status', () => () => <div>Status Mock</div>);
jest.mock('./components/SettingsPage', () => () => <div>Settings Page Mock</div>);
jest.mock('./components/LivePage', () => () => <div>Live Page Mock</div>);
jest.mock('./components/ApiDocsPage', () => () => <div>API Docs Mock</div>);
jest.mock('./components/IncidentPage', () => () => <div>Incidents Mock</div>);
jest.mock('./components/Incident', () => () => <div>Incident Mock</div>);
jest.mock('./components/EntityPage', () => () => <div>Entities Mock</div>);
jest.mock('./components/Entity', () => () => <div>Entity Mock</div>);

describe('App routing shell', () => {
  test('redirects root to settings run tab and renders updated nav order', async () => {
    window.history.pushState({}, '', '/');

    await act(async () => {
      render(<App />);
    });

    expect(await screen.findByText('Settings Page Mock')).toBeTruthy();
    expect(window.location.pathname).toBe('/settings');
    expect(window.location.search).toBe('?tab=run');

    const navLinks = screen.getAllByRole('link').map((link) => link.textContent);
    expect(navLinks).toEqual([
      'Incidents',
      'Entities',
      'Live',
      'Settings',
      'API Docs',
    ]);
  });

  test('redirects monitoring route into settings monitoring tab', async () => {
    window.history.pushState({}, '', '/monitoring');

    await act(async () => {
      render(<App />);
    });

    expect(await screen.findByText('Settings Page Mock')).toBeTruthy();
    expect(window.location.pathname).toBe('/settings');
    expect(window.location.search).toBe('?tab=monitoring');
  });

  test('redirects legacy poi route into settings sources tab', async () => {
    window.history.pushState({}, '', '/poi');

    await act(async () => {
      render(<App />);
    });

    expect(await screen.findByText('Settings Page Mock')).toBeTruthy();
    expect(window.location.pathname).toBe('/settings');
    expect(window.location.search).toBe('?tab=sources');
  });
});
