import { act, render, screen } from '@testing-library/react';
import Status from './Status';

const buildJsonResponse = (body) =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve(body),
  });

beforeEach(() => {
  global.fetch = jest.fn(() =>
    buildJsonResponse({
      status: 'running',
      frame_id: 25,
      total_frames: 100,
      run_id: '2026-03-13_12-00-00',
      module_status: {
        INGESTOR: 'running',
        ANOMALY: 'idle',
      },
      admission: {
        allowed: true,
        reason: null,
      },
      resources: {
        cpu_percent: 15,
        memory_percent: 25,
        module_metrics: {
          ANOMALY: {
            state: 'warning',
            max_queue_depth: 11,
            hottest_queue: 'output_thread',
            queue_depths: {
              output_thread: 11,
            },
          },
        },
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
      },
    })
  );
});

afterEach(() => {
  jest.clearAllMocks();
});

test('renders status summary from the expanded status payload', async () => {
  await act(async () => {
    render(<Status />);
  });

  expect(await screen.findByText('System: running')).toBeTruthy();
  expect(screen.getByText('Run 2026-03-13_12-00-00')).toBeTruthy();
  expect(screen.getByText('INGESTOR: running')).toBeTruthy();
  expect(screen.getByText('ANOMALY: idle')).toBeTruthy();
  expect(screen.getByText('rabbitmq: error')).toBeTruthy();
  expect(screen.getByText('ANOMALY: warning')).toBeTruthy();
  expect(screen.getByText('Frame: 25 / 100')).toBeTruthy();
});

test('shows per-source frame progress when global frame id is missing', async () => {
  global.fetch = jest.fn(() =>
    buildJsonResponse({
      status: 'running',
      frame_id: null,
      total_frames: null,
      run_id: '2026-06-03_15-20-51',
      sources: [
        {
          id: 1,
          enabled: true,
          frames_processed: 57,
          total_frames: null,
          state: 'running',
        },
      ],
      module_status: { INGESTOR: 'running' },
      admission: { allowed: true, reason: null },
      resources: {},
    })
  );

  await act(async () => {
    render(<Status />);
  });

  expect(await screen.findByText('Frames processed: 57')).toBeTruthy();
});
