import { act, render, screen, waitFor } from '@testing-library/react';
import LivePage from './LivePage';

const buildJsonResponse = (body) =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve(body),
  });

beforeEach(() => {
  jest.useFakeTimers();
  global.fetch = jest.fn(() => buildJsonResponse([
    {
      id: 1,
      kind: 'camera_url',
      label: 'North Gate',
      tasks: ['PERSON'],
      enabled: true,
      order: 0,
      source_value: 'http://cams.local/north.mjpeg',
    },
    {
      id: 2,
      kind: 'camera_url',
      label: 'South Gate',
      tasks: ['PERSON', 'BAG'],
      enabled: true,
      order: 1,
      source_value: 'rtsp://cams.local/south',
    },
    {
      id: 3,
      kind: 'video_upload',
      label: 'Uploaded Segment',
      tasks: ['PERSON'],
      enabled: true,
      order: 2,
      source_value: null,
      upload: {
        original_filename: 'segment-01.mp4',
      },
    },
  ]));
});

afterEach(() => {
  jest.runOnlyPendingTimers();
  jest.useRealTimers();
  jest.clearAllMocks();
});

test('renders first two live sources and all uploaded video sources', async () => {
  let container;
  await act(async () => {
    ({ container } = render(<LivePage />));
  });

  expect(await screen.findByText('Live Video')).toBeTruthy();
  expect(await screen.findByText('North Gate')).toBeTruthy();
  expect(await screen.findByText('South Gate')).toBeTruthy();
  expect(await screen.findByText('Uploaded Segment')).toBeTruthy();

  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalledWith(expect.stringMatching(/\/settings\/input-sources$/));
  });

  expect(container.querySelector('img[src="http://localhost:8000/sources/1/preview.mjpeg"]')).toBeTruthy();
  expect(container.querySelector('img[src="http://localhost:8000/sources/2/preview.mjpeg"]')).toBeTruthy();
  expect(container.querySelector('img[src="http://localhost:8000/sources/3/preview.mjpeg"]')).toBeTruthy();
  expect(screen.getByText('segment-01.mp4')).toBeTruthy();
});

test('shows backend preview failure message when preview image load fails', async () => {
  let container;
  await act(async () => {
    ({ container } = render(<LivePage />));
  });

  const previewImage = await waitFor(() => container.querySelector('img[src="http://localhost:8000/sources/1/preview.mjpeg"]'));
  act(() => {
    previewImage.dispatchEvent(new Event('error'));
  });

  expect(await screen.findByText(/The backend preview stream could not be opened/i)).toBeTruthy();
});
