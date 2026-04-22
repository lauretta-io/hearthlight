import { act, render, screen } from '@testing-library/react';
import POIPage from './POIPage';

const buildJsonResponse = (body) =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve(body),
  });

beforeEach(() => {
  global.fetch = jest.fn((url, options = {}) => {
    if (url.endsWith('/genetec/pois') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse([
        {
          id: 12,
          name: 'North Hall Match',
          num_entities: 3,
          last_update_time: '2026-03-14T18:00:00',
          seconds_since_update: 45,
          crop: null,
        },
      ]);
    }
    if (url.endsWith('/register_poi') && options.method === 'POST') {
      return buildJsonResponse({ status: 'ok' });
    }
    return buildJsonResponse({});
  });
});

afterEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
});

test('renders the POI search results grid', async () => {
  await act(async () => {
    render(<POIPage />);
  });

  expect(await screen.findByText('Registered POI Searches')).toBeTruthy();
  expect(await screen.findByText('North Hall Match')).toBeTruthy();
  expect(
    await screen.findByText((content, element) =>
      element?.textContent === '3 matched entities'
    )
  ).toBeTruthy();
  expect(screen.getByText('1 total')).toBeTruthy();
});
