import { render, screen } from '@testing-library/react';
import IncidentCard from './IncidentCard';

test('renders a compact trigger row without resolve or status controls', () => {
  render(
    <IncidentCard
      incident={{
        incident_id: 'AL-20260530-7',
        incident_type: 'ALERT',
        display_title: 'Detector: Person',
        delivery_summary: 'Telegram sent',
        incident_time: '2026-05-30T18:20:00Z',
        status: 'UNCONFIRMED',
        alert_level: 'High',
        location: { camera_id: 2, zone_id: null },
        crop: null,
      }}
    />,
  );

  expect(screen.getByText('Detector: Person')).toBeTruthy();
  expect(screen.getByText('Telegram sent')).toBeTruthy();
  expect(screen.getByText('Camera 2')).toBeTruthy();
  expect(screen.getByText('AL-20260530-7')).toBeTruthy();
  expect(screen.queryByText('Resolve')).toBeNull();
  expect(screen.queryByText(/Status:/i)).toBeNull();
});
