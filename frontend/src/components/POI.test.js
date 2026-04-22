import { act, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import POI from './POI';

const buildJsonResponse = (body) =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve(body),
  });

beforeEach(() => {
  global.fetch = jest.fn((url) => {
    if (String(url).includes('/operations/poi/?poi_id=7')) {
      return buildJsonResponse({
        id: 7,
        name: 'North Hall suspect',
        entities: [
          {
            entity_id: 'P-20260314-22',
            entity_type: 'PERSON',
            last_seen_time: '2026-03-14T18:20:00',
            location: { camera_id: 4, zone_id: 1 },
            crop: null,
          },
        ],
        last_update_time: '2026-03-14T18:21:00',
        seconds_since_update: 45,
        crop: null,
      });
    }
    return buildJsonResponse({});
  });
});

afterEach(() => {
  jest.clearAllMocks();
});

test('renders the POI result detail page', async () => {
  await act(async () => {
    render(
      <MemoryRouter initialEntries={['/poi/7']}>
        <Routes>
          <Route path="/poi/:poiId" element={<POI />} />
        </Routes>
      </MemoryRouter>
    );
  });

  expect(await screen.findByRole('heading', { name: 'North Hall suspect' })).toBeTruthy();
  expect(screen.getByText('Matched Entities')).toBeTruthy();
  expect(screen.getByText('Back to POI searches')).toBeTruthy();
  expect(screen.getByText('45s ago')).toBeTruthy();
  expect(screen.getByText('Entity ID: P-20260314-22')).toBeTruthy();
});
