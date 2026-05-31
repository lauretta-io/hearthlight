import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import Incident from './Incident';

jest.mock('@vidstack/react', () => ({
  MediaCommunitySkin: () => <div>media-skin</div>,
  MediaOutlet: ({ children }) => <div>{children}</div>,
  MediaPlayer: ({ src }) => <video data-testid="incident-video" src={src} />,
  MediaPoster: () => null,
}));

jest.mock('./IncidentCard', () => ({ incident }) => (
  <div>{incident.display_title || incident.incident_id}</div>
));

jest.mock('./ErrorAlert', () => ({ message }) => <div>{message}</div>);
jest.mock('./LoadingAlert', () => ({ message }) => <div>{message}</div>);

const buildJsonResponse = (body) =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve(body),
  });

test('renders a boxed still image for detection triggers', async () => {
  global.fetch = jest.fn(() =>
    buildJsonResponse({
      run_identifier: 'run-1',
      incident_id: 'AL-20260530-113',
      incident_type: 'ALERT',
      display_title: 'Detector: Person',
      media_type: 'image',
      media_event_id: null,
      delivery_summary: 'Telegram sent',
      incident_time: '2026-05-30T00:00:00',
      status: 'UNCONFIRMED',
      location: { camera_id: 1, zone_id: null },
      last_update_time: '2026-05-30T00:00:00',
      last_updated_by: null,
      update_history: [],
      entities: [],
      crop: null,
    }),
  );

  render(
    <MemoryRouter initialEntries={['/incident/AL-20260530-113']}>
      <Routes>
        <Route path="/incident/:incidentId" element={<Incident />} />
      </Routes>
    </MemoryRouter>,
  );

  const image = await screen.findByRole('img', { name: /detector: person/i });
  expect(image.getAttribute('src')).toContain('/operations/incident_image/?incident_id=AL-20260530-113');
  expect(screen.getByRole('link', { name: /back to trigger list/i }).getAttribute('href')).toBe('/incidents?tab=monitoring');
});

test('renders the anomaly clip for anomaly triggers', async () => {
  global.fetch = jest.fn(() =>
    buildJsonResponse({
      run_identifier: 'run-9',
      incident_id: 'AN-20260530-114',
      incident_type: 'ANOMALY',
      display_title: 'Behavior Anomaly: Fighting',
      media_type: 'video',
      media_event_id: 'fight:1:22',
      delivery_summary: null,
      incident_time: '2026-05-30T00:00:00',
      status: 'UNCONFIRMED',
      location: { camera_id: 1, zone_id: null },
      last_update_time: '2026-05-30T00:00:00',
      last_updated_by: null,
      update_history: [],
      entities: [],
      crop: null,
    }),
  );

  render(
    <MemoryRouter initialEntries={['/incident/AN-20260530-114']}>
      <Routes>
        <Route path="/incident/:incidentId" element={<Incident />} />
      </Routes>
    </MemoryRouter>,
  );

  await waitFor(() => {
    const video = screen.getByTestId('incident-video');
    expect(video.getAttribute('src')).toContain('/operations/anomaly_video/?event_id=fight%3A1%3A22');
    expect(video.getAttribute('src')).toContain('run_identifier=run-9');
  });
});
