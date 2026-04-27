import { act, render, screen } from '@testing-library/react';
import MonitoringPage from './MonitoringPage';

const buildJsonResponse = (body) =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve(body),
  });

beforeEach(() => {
  global.fetch = jest.fn((url) => {
    if (url.includes('/monitoring/overview')) {
      return buildJsonResponse({
        generated_at: '2026-03-14T12:00:00Z',
        system_status: 'running',
        current_run_id: '2026-03-14_12-00-00',
        selected_run_identifier: '2026-03-14_12-00-00',
        admission: {
          allowed: true,
          reason: null,
        },
        resources: {
          cpu_percent: 11,
          memory_percent: 22,
          disk_percent: 33,
          gpus: [],
          module_metrics: {
            REID: {
              state: 'warning',
              max_queue_depth: 12,
              hottest_queue: 'database_thread',
              queue_depths: {
                consumer: 0,
                database_thread: 12,
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
          module_status: {
            WEBAPP: 'running',
          },
          model_health: {
            builtin_yolox_s_gpu: {
              model_key: 'builtin_yolox_s_gpu',
              stage: 'detector',
              adapter: 'yolox_detector',
              healthy: true,
              detail: null,
            },
          },
        },
        runs: [
          {
            run_identifier: '2026-03-14_12-00-00',
            status: 'running',
            incident_count: 3,
            entity_count: 5,
            source_count: 2,
            camera_count: 2,
          },
        ],
        sources: [
          {
            id: 1,
            kind: 'camera_url',
            label: 'Checkpoint A',
            tasks: ['PERSON'],
            enabled: true,
            order: 0,
            source_value: 'rtsp://example',
            detector_model_key: 'builtin_yolox_s_gpu',
            tracker_model_key: null,
            reid_model_key: null,
            anomaly_stage_1_model_key: null,
            anomaly_stage_2_model_key: null,
            state: 'running',
          },
        ],
        model_bindings: [
          {
            stage: 'detector',
            model_key: 'builtin_yolox_s_gpu',
            binding_scope: 'default',
            source_id: null,
          },
        ],
        model_registrations: [
          {
            model_key: 'builtin_yolox_s_gpu',
            stage: 'detector',
            adapter: 'yolox_detector',
            display_name: 'YOLOX Small',
          },
          {
            model_key: 'heuristic_presence_stage_1',
            stage: 'anomaly_stage_1',
            adapter: 'heuristic_presence_stage_1',
            display_name: 'Heuristic Presence Stage 1',
          },
          {
            model_key: 'prompt_rules_stage_2',
            stage: 'anomaly_stage_2',
            adapter: 'prompt_rules_stage_2',
            display_name: 'Prompt Rules Stage 2',
          },
        ],
        latest_incidents: [
          {
            run_identifier: '2026-03-14_12-00-00',
            incident_id: 'GUN-20260314-7',
            incident_type: 'GUN',
            status: 'CONFIRMED',
            incident_time: '2026-03-14T12:01:00Z',
            location: {
              camera_id: 4,
              zone_id: 2,
            },
          },
        ],
        latest_entities: [
          {
            run_identifier: '2026-03-14_12-00-00',
            entity_id: 'P-20260314-5',
            entity_type: 'PERSON',
            last_seen_time: '2026-03-14T12:01:30Z',
            associated_incident_ids: ['GUN-20260314-7'],
          },
        ],
        latest_anomalies: [
          {
            event_id: 'heuristic_presence:1:22:presence_resume',
            run_id: '2026-03-14_12-00-00',
            source_id: 1,
            camera_id: 0,
            frame_id: 22,
            stage_1_model_key: 'heuristic_presence_stage_1',
            stage_2_model_key: 'prompt_rules_stage_2',
            model_key: 'prompt_rules_stage_2',
            category: 'presence_resume',
            score: 0.8,
            reasoning: 'Observed 2 tracked objects after inactivity window.',
            asset_references: [],
          },
        ],
        recent_events: [
          {
            created_at: '2026-03-14T12:02:00Z',
            event_type: 'system_start',
            severity: 'info',
            message: 'system start published',
          },
        ],
        feed_endpoints: [
          {
            name: 'Algorithm Feed',
            path: '/feeds/algorithm',
            description: 'Combined source, resource, incident, entity, and anomaly output for a run.',
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

test('renders monitoring overview and feed endpoint catalog', async () => {
  await act(async () => {
    render(<MonitoringPage />);
  });

  expect(await screen.findByText('Monitoring')).toBeTruthy();
  expect(screen.getByText('Feed Endpoints')).toBeTruthy();
  expect(screen.getByText('Checkpoint A')).toBeTruthy();
  expect(screen.getByText('GUN-20260314-7')).toBeTruthy();
  expect(screen.getByText('Dependencies')).toBeTruthy();
  expect(screen.getByText('Model Health')).toBeTruthy();
  expect(screen.getByText('Anomalies')).toBeTruthy();
  expect(screen.getByText('Module Backpressure')).toBeTruthy();
  expect(screen.getAllByText('YOLOX Small').length).toBeGreaterThan(0);
  expect(screen.getByText('database_thread at depth 12')).toBeTruthy();
  expect(screen.getByText('connection refused')).toBeTruthy();
  expect(screen.getByText(/\/feeds\/algorithm/)).toBeTruthy();
  expect(screen.getByText('presence_resume')).toBeTruthy();
});
