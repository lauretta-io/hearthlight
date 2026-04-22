import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import ControlPage from './ControlPage';

const buildJsonResponse = (body) =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve(body),
  });

beforeEach(() => {
  global.fetch = jest.fn((url, options = {}) => {
    if (url.endsWith('/sources') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse([
        {
          id: 1,
          kind: 'camera_url',
          label: 'Checkpoint A',
          tasks: ['PERSON', 'BAG'],
          enabled: true,
          order: 0,
          source_value: 'rtsp://example',
        },
      ]);
    }
    if (url.endsWith('/sources') && options.method === 'PUT') {
      return buildJsonResponse([
        {
          id: 1,
          kind: 'camera_url',
          label: 'Checkpoint A',
          tasks: ['PERSON', 'BAG'],
          enabled: true,
          order: 0,
          source_value: 'rtsp://example',
        },
      ]);
    }
    if (url.endsWith('/status')) {
      return buildJsonResponse({
        status: 'idle',
        module_status: {
          INGESTOR: 'idle',
          REID: 'idle',
          ASSOCIATION: 'idle',
        },
        sources: [],
        admission: {
          allowed: true,
          reason: null,
        },
      });
    }
    if (url.endsWith('/system/resources')) {
      return buildJsonResponse({
        cpu_percent: 10,
        memory_percent: 20,
        disk_percent: 30,
        gpus: [],
        dependency_status: {
          database: {
            status: 'ok',
            detail: null,
          },
          rabbitmq: {
            status: 'error',
            detail: 'connection refused',
          },
        },
        module_metrics: {
          INGESTOR: {
            state: 'warning',
            max_queue_depth: 14,
            hottest_queue: 'downstream_max',
            queue_depths: {
              frames_thread: 1,
              downstream_max: 14,
            },
          },
        },
        admission: {
          allowed: false,
          reason: 'rabbitmq: connection refused',
        },
        module_status: {
          WEBAPP: 'running',
        },
      });
    }
    if (url.endsWith('/start')) {
      return buildJsonResponse({
        status: 'starting',
        run_id: '2026-03-13_12-00-00',
      });
    }
    if (url.endsWith('/stop')) {
      return buildJsonResponse({
        status: 'stopping',
      });
    }
    return buildJsonResponse({});
  });
});

afterEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
});

test('renders persisted mixed sources and resource panel', async () => {
  await act(async () => {
    render(<ControlPage />);
  });

  expect(await screen.findByText('Run Control')).toBeTruthy();
  expect(screen.getByText('Source Queue')).toBeTruthy();
  expect(await screen.findByDisplayValue('Checkpoint A')).toBeTruthy();
  expect(screen.getByText('Resources And Admission')).toBeTruthy();
  expect(screen.getByText('rabbitmq')).toBeTruthy();
  expect(screen.getByText('connection refused')).toBeTruthy();
  expect(screen.getByText(/Queue state warning/)).toBeTruthy();
});

test('saves sources before starting a run', async () => {
  await act(async () => {
    render(<ControlPage />);
  });

  await screen.findByDisplayValue('Checkpoint A');
  await act(async () => {
    fireEvent.click(screen.getByText('Start'));
  });

  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/sources$/),
      expect.objectContaining({ method: 'PUT' }),
    );
  });
  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/start$/),
      expect.objectContaining({ method: 'POST' }),
    );
  });
});
