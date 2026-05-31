import { act, fireEvent, render, screen } from '@testing-library/react';
import ModelLogsPage from './ModelLogsPage';

const buildJsonResponse = (body) =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve(body),
  });

beforeEach(() => {
  global.EventSource = jest.fn(() => ({
    addEventListener: jest.fn(),
    close: jest.fn(),
  }));
  global.fetch = jest.fn((url) => {
    if (url.includes('/sources')) {
      return buildJsonResponse([
        {
          id: 1,
          label: 'Camera 1',
        },
      ]);
    }
    if (url.includes('/model-logs')) {
      return buildJsonResponse({
        page: 1,
        page_size: 20,
        total: 2,
        has_more: false,
        records: [
          {
            id: 101,
            created_at: '2026-05-16T12:00:00Z',
            run_id: '2026-05-16_12-00-00',
            source_id: 1,
            source_label: 'Camera 1',
            camera_id: 0,
            stage: 'detector',
            model_key: 'builtin_yolox_s_cpu',
            model_display_name: 'YOLOX Small (CPU)',
            frame_id: 88,
            result_summary: '2 detections · person x1 (max 0.94); backpack x1 (max 0.78)',
            result_payload: {
              detection_count: 2,
            },
          },
          {
            id: 102,
            created_at: '2026-05-16T12:00:03Z',
            run_id: '2026-05-16_12-00-00',
            source_id: 1,
            source_label: 'Camera 1',
            camera_id: 0,
            stage: 'anomaly_stage_2',
            model_key: 'lm_studio_stage_2',
            model_display_name: 'LM Studio',
            frame_id: 89,
            result_summary: 'No anomaly returned · Score 0.18',
            result_payload: {
              score: 0.18,
            },
          },
        ],
      });
    }
    return buildJsonResponse({});
  });
});

afterEach(() => {
  jest.clearAllMocks();
  delete global.EventSource;
});

test('renders model log filters and rows', async () => {
  await act(async () => {
    render(<ModelLogsPage />);
  });

  expect(await screen.findByText('Model Logs')).toBeTruthy();
  expect(
    screen.getByRole('heading', { name: 'Filters', level: 3 }).compareDocumentPosition(
      screen.getByRole('heading', { name: 'Log Results', level: 3 }),
    ) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(screen.getAllByText('Camera 1').length).toBeGreaterThan(0);
  expect(screen.getByText('YOLOX Small (CPU)')).toBeTruthy();
  expect(screen.getByText(/2 detections/i)).toBeTruthy();

  fireEvent.click(screen.getByRole('button', { name: /2 detections/i }));
  expect(screen.getByText(/"detection_count": 2/)).toBeTruthy();
});

test('filters immediately on the loaded records without extra fetches', async () => {
  await act(async () => {
    render(<ModelLogsPage />);
  });

  await screen.findByText('LM Studio');
  const fetchCountAfterLoad = global.fetch.mock.calls.length;

  fireEvent.change(screen.getByDisplayValue('All model types'), {
    target: { value: 'anomaly_stage_2' },
  });

  expect(await screen.findByText('LM Studio')).toBeTruthy();
  expect(screen.queryByText('YOLOX Small (CPU)')).toBeNull();
  expect(global.fetch.mock.calls.length).toBe(fetchCountAfterLoad);
});
