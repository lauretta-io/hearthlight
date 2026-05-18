import { act, fireEvent, render, screen } from '@testing-library/react';
import ModelLogsPage from './ModelLogsPage';

const buildJsonResponse = (body) =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve(body),
  });

beforeEach(() => {
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
        total: 1,
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
        ],
      });
    }
    return buildJsonResponse({});
  });
});

afterEach(() => {
  jest.clearAllMocks();
});

test('renders model log filters and rows', async () => {
  await act(async () => {
    render(<ModelLogsPage />);
  });

  expect(await screen.findByText('Model Logs')).toBeTruthy();
  expect(screen.getAllByText('Camera 1').length).toBeGreaterThan(0);
  expect(screen.getByText('YOLOX Small (CPU)')).toBeTruthy();
  expect(screen.getByText(/2 detections/i)).toBeTruthy();

  fireEvent.click(screen.getByRole('button', { name: /2 detections/i }));
  expect(screen.getByText(/"detection_count": 2/)).toBeTruthy();
});
