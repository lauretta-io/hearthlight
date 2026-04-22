import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SettingsPage from './SettingsPage';

const buildJsonResponse = (body) =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve(body),
  });

beforeEach(() => {
  global.fetch = jest.fn((url, options = {}) => {
    if (url.endsWith('/settings/input-sources') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse([
        {
          id: 1,
          kind: 'camera_url',
          label: 'Gate 1',
          tasks: ['PERSON'],
          enabled: true,
          order: 0,
          source_value: 'rtsp://gate-1',
          detector_model_key: null,
          tracker_model_key: null,
          reid_model_key: null,
          anomaly_model_key: null,
        },
      ]);
    }
    if (url.endsWith('/models')) {
      return buildJsonResponse([
        { model_key: 'builtin_rtdetr', stage: 'detector', adapter: 'rtdetr_detector' },
        { model_key: 'builtin_cmtrack', stage: 'tracker', adapter: 'cmtrack_tracker' },
        { model_key: 'builtin_reid', stage: 'reid', adapter: 'legacy_reid' },
        { model_key: 'heuristic_presence', stage: 'anomaly', adapter: 'heuristic_presence' },
      ]);
    }
    if (url.endsWith('/model-bindings') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse([
        { stage: 'detector', model_key: 'builtin_rtdetr', binding_scope: 'default', source_id: null },
        { stage: 'tracker', model_key: 'builtin_cmtrack', binding_scope: 'default', source_id: null },
        { stage: 'reid', model_key: 'builtin_reid', binding_scope: 'default', source_id: null },
        { stage: 'anomaly', model_key: 'heuristic_presence', binding_scope: 'default', source_id: null },
      ]);
    }
    if (url.endsWith('/export-sinks')) {
      return buildJsonResponse([
        {
          sink_key: 'kafka_default',
          adapter: 'kafka_json',
          enabled: false,
          bootstrap_servers: ['localhost:9092'],
          topics: {},
          batch: {},
          health: { status: 'ok', detail: null },
        },
      ]);
    }
    if (url.endsWith('/settings/input-sources') && options.method === 'PUT') {
      return buildJsonResponse([
        {
          id: 1,
          kind: 'camera_url',
          label: 'Gate 1',
          tasks: ['PERSON'],
          enabled: true,
          order: 0,
          source_value: 'rtsp://gate-1',
          detector_model_key: null,
          tracker_model_key: null,
          reid_model_key: null,
          anomaly_model_key: null,
        },
      ]);
    }
    if (url.endsWith('/model-bindings') && options.method === 'PUT') {
      return buildJsonResponse([
        { stage: 'detector', model_key: 'builtin_rtdetr', binding_scope: 'default', source_id: null },
        { stage: 'tracker', model_key: 'builtin_cmtrack', binding_scope: 'default', source_id: null },
        { stage: 'reid', model_key: 'builtin_reid', binding_scope: 'default', source_id: null },
        { stage: 'anomaly', model_key: 'heuristic_presence', binding_scope: 'default', source_id: null },
      ]);
    }
    return buildJsonResponse({});
  });
});

afterEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
});

test('renders source settings and saves to settings endpoint', async () => {
  await act(async () => {
    render(
      <MemoryRouter initialEntries={['/settings?tab=sources']}>
        <SettingsPage />
      </MemoryRouter>,
    );
  });

  expect(await screen.findByText('Settings')).toBeTruthy();
  expect(screen.getByRole('tab', { name: 'Sources' }).getAttribute('aria-selected')).toBe('true');
  expect(await screen.findByDisplayValue('Gate 1')).toBeTruthy();
  expect(await screen.findByText('Default Model Bindings')).toBeTruthy();

  await act(async () => {
    fireEvent.click(screen.getByText('Save Source Settings'));
  });

  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/settings\/input-sources$/),
      expect.objectContaining({ method: 'PUT' }),
    );
  });
});

test('renders initialization tab content when selected', async () => {
  await act(async () => {
    render(
      <MemoryRouter initialEntries={['/settings?tab=initialization']}>
        <SettingsPage />
      </MemoryRouter>,
    );
  });

  expect(await screen.findByText('Repository Initialization')).toBeTruthy();
  expect(screen.getByText(/Recommended Launch Command/)).toBeTruthy();
  expect(screen.getByText(/python3 run\/run\.py start --mode api --template active --profile cpu --open-dashboard/)).toBeTruthy();
});
