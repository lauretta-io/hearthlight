import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import IncidentPage from './IncidentPage';

jest.mock('./IncidentCard', () => ({ incident }) => (
  <div>{`Incident:${incident.incident_id}`}</div>
));

jest.mock('./ErrorAlert', () => ({ message }) => <div>{message}</div>);
jest.mock('./LoadingAlert', () => ({ message }) => <div>{message}</div>);

const buildJsonResponse = (body) =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve(body),
  });

class MockEventSource {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.listeners = {};
    this.onerror = null;
    MockEventSource.instances.push(this);
  }

  addEventListener(eventName, handler) {
    this.listeners[eventName] = handler;
  }

  emit(eventName, data = {}) {
    const handler = this.listeners[eventName];
    if (handler) {
      handler({ data: JSON.stringify(data) });
    }
  }

  close() {}
}

beforeEach(() => {
  jest.useFakeTimers();
  MockEventSource.instances = [];
  global.EventSource = MockEventSource;

  let runFetchCount = 0;
  global.fetch = jest.fn((url) => {
    if (url.endsWith('/operations/runs')) {
      runFetchCount += 1;
      return buildJsonResponse(runFetchCount === 1 ? [] : ['run-1']);
    }
    if (url.includes('/operations/incidents?') && url.includes('run_identifier=run-1')) {
      return buildJsonResponse([
        {
          run_identifier: 'run-1',
          incident_id: 'GUN-20260415-1',
          incident_type: 'GUN',
          incident_time: '2026-04-15T00:00:00',
          status: 'UNCONFIRMED',
          location: { camera_id: 7, zone_id: null },
          last_update_time: '2026-04-15T00:00:00',
          last_updated_by: null,
          crop: null,
        },
      ]);
    }
    if (url.includes('/feeds/algorithm?run_identifier=run-1')) {
      return buildJsonResponse({
        anomalies: [
          {
            event_id: 'heuristic_presence:1:22:presence_resume',
            run_id: 'run-1',
            source_id: 1,
            frame_id: 22,
            event_time: '2026-04-15T18:42:00',
            title: 'Behavior Anomaly: Presence Resume',
            model_key: 'heuristic_presence',
            category: 'presence_resume',
            score: 0.8,
            reasoning: 'Observed behavior anomaly: Presence Resume.',
            visible_items: ['person'],
            visible_activities: ['presence resume'],
            asset_references: [],
          },
        ],
      });
    }
    return buildJsonResponse([]);
  });
});

afterEach(() => {
  jest.runOnlyPendingTimers();
  jest.useRealTimers();
  jest.clearAllMocks();
  delete global.EventSource;
});

test('auto-follows a run that appears after the page loads via stream update', async () => {
  await act(async () => {
    render(<IncidentPage />);
  });

  expect(await screen.findByText('No runs in database')).toBeTruthy();
  expect(MockEventSource.instances).toHaveLength(1);

  await act(async () => {
    MockEventSource.instances[0].emit('runs.updated', {
      run_identifiers: ['run-1'],
    });
  });

  expect(await screen.findByText('Incident:GUN-20260415-1')).toBeTruthy();
  expect(await screen.findByText('Behavior Anomaly: Presence Resume')).toBeTruthy();

  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/operations\/incidents\?.*include_crop=true.*run_identifier=run-1/),
    );
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/feeds\/algorithm\?run_identifier=run-1&limit=50$/),
    );
  });
});

test('opens a modal with clip video and anomaly summary from the feed', async () => {
  await act(async () => {
    render(<IncidentPage />);
  });

  await act(async () => {
    MockEventSource.instances[0].emit('runs.updated', {
      run_identifiers: ['run-1'],
    });
  });

  fireEvent.click(await screen.findByRole('button', { name: /behavior anomaly: presence resume/i }));

  const dialog = screen.getByRole('dialog');
  expect(dialog).toBeTruthy();
  expect(screen.getAllByText('Behavior Anomaly: Presence Resume').length).toBeGreaterThan(0);
  expect(screen.getByText('Summary')).toBeTruthy();
  expect(dialog.textContent).toContain(
    'Observed behavior anomaly: Presence Resume.',
  );
  expect(dialog.textContent).toContain('Visible Items');
  expect(dialog.textContent).toContain('person');
  expect(dialog.textContent).toContain('Visible Activities');
  expect(dialog.textContent).toContain('presence resume');

  const video = dialog.querySelector('video');
  expect(video).toBeTruthy();
  expect(video.getAttribute('src')).toContain('/operations/anomaly_video/?');
  expect(video.getAttribute('src')).toContain(
    'event_id=heuristic_presence%3A1%3A22%3Apresence_resume',
  );
  expect(video.getAttribute('src')).toContain('run_identifier=run-1');
  expect(video.getAttribute('src')).toContain('duration=10');
});

test('can switch alert list to all persisted alerts', async () => {
  global.fetch = jest.fn((url) => {
    if (url.endsWith('/operations/runs')) {
      return buildJsonResponse(['run-1']);
    }
    if (url.includes('/operations/incidents?') && url.includes('filter_mode=all')) {
      return buildJsonResponse([
        {
          run_identifier: 'run-0',
          incident_id: 'AL-20260415-9',
          incident_type: 'ALERT',
          incident_time: '2026-04-15T00:00:00',
          status: 'UNCONFIRMED',
          location: { camera_id: 3, zone_id: null },
          last_update_time: '2026-04-15T00:00:00',
          last_updated_by: null,
          crop: null,
        },
      ]);
    }
    if (url.includes('/operations/incidents?') && url.includes('run_identifier=run-1')) {
      return buildJsonResponse([]);
    }
    if (url.includes('/feeds/algorithm?run_identifier=run-1')) {
      return buildJsonResponse({ anomalies: [] });
    }
    return buildJsonResponse([]);
  });

  await act(async () => {
    render(<IncidentPage />);
  });

  fireEvent.change(await screen.findByLabelText('Alert View:'), {
    target: { value: 'all' },
  });

  expect(await screen.findByText('Incident:AL-20260415-9')).toBeTruthy();
});
