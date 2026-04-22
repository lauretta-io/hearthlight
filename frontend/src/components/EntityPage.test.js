import { act, render, screen, waitFor } from '@testing-library/react';
import EntityPage from './EntityPage';

jest.mock('./EntityCard', () => ({ entity }) => (
  <div>{`Entity:${entity.entity_id}`}</div>
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
    if (url.includes('/operations/entities/?run_identifier=run-1')) {
      return buildJsonResponse([
        {
          entity_id: 'person-20260415-1',
          entity_type: 'PERSON',
          last_seen_time: '2026-04-15T00:00:00',
          location: { camera_id: 7, zone_id: null },
          crop: null,
        },
      ]);
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

test('auto-follows a run and entity update after the page loads', async () => {
  await act(async () => {
    render(<EntityPage />);
  });

  expect(await screen.findByText('No runs in database')).toBeTruthy();
  expect(MockEventSource.instances).toHaveLength(1);

  await act(async () => {
    MockEventSource.instances[0].emit('runs.updated', {
      run_identifiers: ['run-1'],
    });
    MockEventSource.instances[0].emit('entities.updated', {
      run_ids: [1],
      entity_ids: [1],
    });
  });

  expect(await screen.findByText('Entity:person-20260415-1')).toBeTruthy();

  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/operations\/entities\/\?run_identifier=run-1&include_crop=true$/),
    );
  });
});
