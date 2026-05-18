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
    if (url.includes('/operations/incidents?run_identifier=run-1')) {
      return buildJsonResponse([
        {
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
            title: 'Anomaly found: person; presence resume',
            model_key: 'heuristic_presence',
            category: 'presence_resume',
            score: 0.8,
            reasoning: 'Observed 2 tracked objects after inactivity window.',
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
  expect(await screen.findByText('presence_resume')).toBeTruthy();

  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/operations\/incidents\?run_identifier=run-1&include_crop=true$/),
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

  fireEvent.click(await screen.findByRole('button', { name: /presence_resume/i }));

  const dialog = screen.getByRole('dialog');
  expect(dialog).toBeTruthy();
  expect(screen.getByText('Anomaly found: person; presence resume')).toBeTruthy();
  expect(screen.getByText('Summary')).toBeTruthy();
  expect(dialog.textContent).toContain(
    'Observed 2 tracked objects after inactivity window.',
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
