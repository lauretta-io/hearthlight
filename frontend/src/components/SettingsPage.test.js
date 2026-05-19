import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SettingsPage from './SettingsPage';

const buildJsonResponse = (body) =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve(body),
  });

beforeEach(() => {
  global.fetch = jest.fn((url, options = {}) => {
    if (url.endsWith('/settings/input-sources') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse([
        {
          id: 1,
          kind: 'camera_url',
          label: 'Gate 1',
          tasks: ['PERSON'],
          enabled: true,
          order: 0,
          source_value: 'rtsp://gate-1',
          detector_model_key: null,
          tracker_model_key: null,
          reid_model_key: null,
          anomaly_stage_1_model_key: null,
          anomaly_stage_2_model_key: null,
        },
      ]);
    }
    if (url.endsWith('/settings/appearance') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse({
        theme_key: 'fidelity-light',
      });
    }
    if (url.endsWith('/model-options')) {
      return buildJsonResponse({
        model_zoo: {
          package_name: 'hearthlight_model_zoo',
          commit_sha: '273feddf9e381b8de143c83deadf23fc9c4c4184',
          commit_short: '273feddf',
          resolved_from: 'requirements_pin',
          catalog_available: true,
        },
        mounted_models: {
          detector: ['builtin_yolox_s_gpu'],
          tracker: ['builtin_bytetrack'],
          anomaly_stage_1: ['heuristic_presence_stage_1'],
          anomaly_stage_2: ['prompt_rules_stage_2'],
        },
        stages: [
          {
            stage: 'detector',
            options: [
              {
                model_key: 'builtin_yolox_s_gpu',
                display_name: 'YOLOX Small (GPU)',
                stage: 'detector',
                adapter: 'yolox_detector',
                is_mounted: true,
                capabilities: {
                  tasks: ['PERSON', 'BAG'],
                  classes: ['person', 'bicycle', 'car', 'backpack', 'handbag', 'suitcase'],
                },
              },
              {
                model_key: 'builtin_yolox_tiny_cpu',
                display_name: 'YOLOX Tiny (CPU)',
                stage: 'detector',
                adapter: 'yolox_detector',
                is_mounted: false,
                capabilities: {
                  tasks: ['PERSON', 'BAG'],
                  classes: ['person', 'bicycle', 'car', 'backpack', 'handbag', 'suitcase'],
                },
              },
            ],
          },
          {
            stage: 'tracker',
            options: [
              { model_key: 'builtin_bytetrack', display_name: 'ByteTrack', stage: 'tracker', adapter: 'bytetrack_tracker', is_mounted: true },
            ],
          },
          {
            stage: 'anomaly_stage_1',
            options: [
              { model_key: 'heuristic_presence_stage_1', display_name: 'Heuristic Presence Stage 1', stage: 'anomaly_stage_1', adapter: 'heuristic_presence_stage_1', is_mounted: true },
            ],
          },
          {
            stage: 'anomaly_stage_2',
            options: [
              { model_key: 'prompt_rules_stage_2', display_name: 'Prompt Rules Stage 2', stage: 'anomaly_stage_2', adapter: 'prompt_rules_stage_2', is_mounted: true },
              { model_key: 'claude_compatible_stage_2', display_name: 'Claude-Compatible Anomaly API', stage: 'anomaly_stage_2', adapter: 'claude_compatible_stage_2', is_mounted: false },
            ],
          },
        ],
      });
    }
    if (url.endsWith('/model-bindings') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse([
        { stage: 'detector', model_key: 'builtin_yolox_s_gpu', binding_scope: 'default', source_id: null },
        { stage: 'tracker', model_key: 'builtin_bytetrack', binding_scope: 'default', source_id: null },
        { stage: 'anomaly_stage_1', model_key: 'heuristic_presence_stage_1', binding_scope: 'default', source_id: null },
        { stage: 'anomaly_stage_2', model_key: 'prompt_rules_stage_2', binding_scope: 'default', source_id: null },
      ]);
    }
    if (url.endsWith('/settings/anomaly-prompts') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse({
        anomaly_items: [
          { item: 'weapon' },
        ],
        anomaly_behaviors: ['running'],
      });
    }
    if (url.endsWith('/settings/trigger-rules') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse([
        {
          id: 11,
          source_ids: [1],
          enabled: true,
          rule_label: 'Bag Watch',
          rule_kind: 'detector',
          signal_family: 'detector',
          target_key: 'BAG',
          min_confidence: 0.7,
          anomaly_cutoff: null,
          alert_level: 'high',
        },
      ]);
    }
    if (url.endsWith('/settings/alert-rules') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse([
        {
          id: 11,
          source_id: 1,
          enabled: true,
          rule_label: 'Bag Watch',
          signal_family: 'detector',
          target_key: 'BAG',
          min_confidence: 0.7,
          alert_level: 'high',
        },
      ]);
    }
    if (url.endsWith('/settings/alert-rule-options') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse({
        sources: [
          {
            source_id: 1,
            source_label: 'Gate 1',
            detector_model_key: 'builtin_yolox_s_gpu',
            anomaly_stage_1_model_key: 'heuristic_presence_stage_1',
            anomaly_stage_2_model_key: 'prompt_rules_stage_2',
            signal_options: [
              {
                signal_family: 'detector',
                options: [
                  { key: 'PERSON', label: 'PERSON', description: 'Matches detector class: person' },
                  { key: 'BAG', label: 'BAG', description: 'Matches detector classes: backpack, handbag, suitcase' },
                ],
                unavailable_reason: null,
              },
              {
                signal_family: 'anomaly_object',
                options: [
                  { key: 'weapon', label: 'weapon' },
                ],
                unavailable_reason: null,
              },
              {
                signal_family: 'anomaly_activity',
                options: [
                  { key: 'running', label: 'running' },
                ],
                unavailable_reason: null,
              },
            ],
          },
        ],
      });
    }
    if (url.endsWith('/settings/telegram-trigger-subscriptions') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse([
        {
          id: 41,
          enabled: true,
          subscription_label: 'Ops Chat',
          bot_token: '********',
          chat_id: '-1001234567890',
        },
      ]);
    }
    if (url.endsWith('/settings/claude-api-connectors') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse([
        {
          id: 61,
          enabled: true,
          connector_label: 'Local Claude Demo',
          base_url: 'http://localhost:8787/v1/messages',
          auth_token: '********',
          timeout_seconds: 10,
          retry_count: 1,
        },
      ]);
    }
    if (url.endsWith('/settings/claude-anomaly-model') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse({
        enabled: true,
        base_url: 'http://localhost:8788/v1/messages',
        auth_token: '********',
        model_name: 'demo-anomaly-model',
        timeout_seconds: 10,
        retry_count: 1,
        prompt_template: 'Return Hearthlight anomaly JSON.',
      });
    }
    if (url.endsWith('/settings/action-connectors') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse([
        {
          id: 71,
          enabled: true,
          action_type: 'philips_hue',
          connector_label: 'Demo Hue',
          base_url: 'http://localhost:8790/actions',
          auth_token: '********',
          command: 'flash_scene',
          target: 'lobby-light',
          parameters: { color: 'red' },
          timeout_seconds: 10,
          retry_count: 1,
        },
      ]);
    }
    if (url.endsWith('/settings/apple-message-trigger-subscriptions') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse([
        {
          id: 51,
          enabled: true,
          subscription_label: 'Ops iMessage',
          recipient_handle: '+15551234567',
          service: 'iMessage',
        },
      ]);
    }
    if (url.endsWith('/settings/input-sources') && options.method === 'PUT') {
      return buildJsonResponse([
        {
          id: 1,
          kind: 'camera_url',
          label: 'Gate 1',
          tasks: ['PERSON'],
          enabled: true,
          order: 0,
          source_value: 'rtsp://gate-1',
          detector_model_key: null,
          tracker_model_key: null,
          reid_model_key: null,
          anomaly_stage_1_model_key: null,
          anomaly_stage_2_model_key: null,
        },
      ]);
    }
    if (url.endsWith('/model-bindings') && options.method === 'PUT') {
      return buildJsonResponse([
        { stage: 'detector', model_key: 'builtin_yolox_s_gpu', binding_scope: 'default', source_id: null },
        { stage: 'tracker', model_key: 'builtin_bytetrack', binding_scope: 'default', source_id: null },
        { stage: 'anomaly_stage_1', model_key: 'heuristic_presence_stage_1', binding_scope: 'default', source_id: null },
        { stage: 'anomaly_stage_2', model_key: 'prompt_rules_stage_2', binding_scope: 'default', source_id: null },
      ]);
    }
    if (url.endsWith('/settings/trigger-rules') && options.method === 'PUT') {
      return buildJsonResponse([
        {
          id: 11,
          source_ids: [1],
          enabled: true,
          rule_label: 'Bag Watch',
          rule_kind: 'detector',
          signal_family: 'detector',
          target_key: 'BAG',
          min_confidence: 0.7,
          anomaly_cutoff: null,
          alert_level: 'high',
        },
      ]);
    }
    if (url.endsWith('/settings/alert-rules') && options.method === 'PUT') {
      return buildJsonResponse([
        {
          id: 11,
          source_id: 1,
          enabled: true,
          rule_label: 'Bag Watch',
          signal_family: 'detector',
          target_key: 'BAG',
          min_confidence: 0.7,
          alert_level: 'high',
        },
      ]);
    }
    if (url.endsWith('/settings/telegram-trigger-subscriptions') && options.method === 'PUT') {
      return buildJsonResponse([
        {
          id: 41,
          enabled: true,
          subscription_label: 'Ops Chat',
          bot_token: '********',
          chat_id: '-1001234567890',
        },
      ]);
    }
    if (url.endsWith('/settings/telegram-trigger-subscriptions/test') && options.method === 'POST') {
      return buildJsonResponse({
        status: 'sent',
        detail: 'Telegram test message sent.',
      });
    }
    if (url.endsWith('/settings/claude-api-connectors') && options.method === 'PUT') {
      return buildJsonResponse([
        {
          id: 61,
          enabled: true,
          connector_label: 'Local Claude Demo',
          base_url: 'http://localhost:8787/v1/messages',
          auth_token: '********',
          timeout_seconds: 10,
          retry_count: 1,
        },
      ]);
    }
    if (url.endsWith('/settings/claude-api-connectors/test') && options.method === 'POST') {
      return buildJsonResponse({
        status: 'sent',
        detail: 'Third-party API test payload sent.',
      });
    }
    if (url.endsWith('/settings/claude-anomaly-model') && options.method === 'PUT') {
      return buildJsonResponse({
        enabled: true,
        base_url: 'http://localhost:8788/v1/messages',
        auth_token: '********',
        model_name: 'demo-anomaly-model',
        timeout_seconds: 10,
        retry_count: 1,
        prompt_template: 'Return Hearthlight anomaly JSON.',
      });
    }
    if (url.endsWith('/settings/claude-anomaly-model/test') && options.method === 'POST') {
      return buildJsonResponse({
        status: 'sent',
        detail: 'Claude-compatible anomaly model test request sent.',
        result: { promote: true, category: 'anomaly_event', score: 0.9 },
      });
    }
    if (url.endsWith('/settings/action-connectors') && options.method === 'PUT') {
      return buildJsonResponse([
        {
          id: 71,
          enabled: true,
          action_type: 'philips_hue',
          connector_label: 'Demo Hue',
          base_url: 'http://localhost:8790/actions',
          auth_token: '********',
          command: 'flash_scene',
          target: 'lobby-light',
          parameters: { color: 'red' },
          timeout_seconds: 10,
          retry_count: 1,
        },
      ]);
    }
    if (url.endsWith('/settings/action-connectors/test') && options.method === 'POST') {
      return buildJsonResponse({
        status: 'sent',
        detail: 'Action connector test payload sent.',
      });
    }
    if (url.endsWith('/settings/apple-message-trigger-subscriptions') && options.method === 'PUT') {
      return buildJsonResponse([
        {
          id: 51,
          enabled: true,
          subscription_label: 'Ops iMessage',
          recipient_handle: '+15551234567',
          service: 'iMessage',
        },
      ]);
    }
    if (url.endsWith('/settings/apple-message-trigger-subscriptions/test') && options.method === 'POST') {
      return buildJsonResponse({
        status: 'sent',
        detail: 'Apple Messages test message sent.',
      });
    }
    if (url.endsWith('/settings/anomaly-prompts') && options.method === 'PUT') {
      return buildJsonResponse({
        anomaly_items: [
          { item: 'weapon' },
        ],
        anomaly_behaviors: ['running'],
      });
    }
    if (url.endsWith('/settings/appearance') && options.method === 'PUT') {
      return buildJsonResponse({
        theme_key: 'fidelity-dark',
      });
    }
    if (url.endsWith('/demo/triggers/fire') && options.method === 'POST') {
      return buildJsonResponse({
        status: 'sent',
        detail: 'Demo trigger queued.',
      });
    }
    return buildJsonResponse({});
  });
});

afterEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
});

test('renders source settings and saves to settings endpoint', async () => {
  await act(async () => {
    render(
      <MemoryRouter initialEntries={['/settings?tab=sources']}>
        <SettingsPage />
      </MemoryRouter>,
    );
  });

  expect(await screen.findByText('Settings')).toBeTruthy();
  expect(screen.getByRole('tab', { name: 'Sources' }).getAttribute('aria-selected')).toBe('true');
  expect(screen.queryByRole('tab', { name: 'Rules' })).toBeNull();
  expect(screen.queryByRole('tab', { name: 'Connectors' })).toBeNull();
  expect(await screen.findByDisplayValue('Gate 1')).toBeTruthy();
  expect(await screen.findByText('Default Model Bindings')).toBeTruthy();
  expect(screen.getByText('Enable Video AI')).toBeTruthy();
  expect(screen.getByDisplayValue('1')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Update Source Settings' })).toBeTruthy();

  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Update Source Settings' }));
  });

  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/settings\/input-sources$/),
      expect.objectContaining({ method: 'PUT' }),
    );
  });
});

test('hides source model overrides when video AI is disabled', async () => {
  await act(async () => {
    render(
      <MemoryRouter initialEntries={['/settings?tab=sources']}>
        <SettingsPage />
      </MemoryRouter>,
    );
  });

  expect(await screen.findByDisplayValue('Gate 1')).toBeTruthy();
  expect(screen.getByText('Detector Override')).toBeTruthy();

  fireEvent.click(screen.getByLabelText('Enable Video AI'));

  await waitFor(() => {
    expect(screen.queryByText('Detector Override')).toBeNull();
  });
  expect(screen.getByText(/video ai is disabled for this source/i)).toBeTruthy();
});

test('renders initialization tab content when selected', async () => {
  await act(async () => {
    render(
      <MemoryRouter initialEntries={['/settings?tab=initialization']}>
        <SettingsPage />
      </MemoryRouter>,
    );
  });

  expect(await screen.findByText('Repository Initialization')).toBeTruthy();
  expect(screen.getByText(/Recommended Launch Command/)).toBeTruthy();
  expect(screen.getByText(/python3 run\/run\.py start --template active --profile cpu --open-dashboard/)).toBeTruthy();
});

test('renders stage 2 anomaly config and saves structured anomaly settings', async () => {
  await act(async () => {
    render(
      <MemoryRouter initialEntries={['/settings?tab=sources']}>
        <SettingsPage />
      </MemoryRouter>,
    );
  });

  expect(await screen.findByText('Anomaly Prompt Settings')).toBeTruthy();
  expect(screen.getByDisplayValue('weapon')).toBeTruthy();
  expect(screen.getByDisplayValue('running')).toBeTruthy();

  await act(async () => {
    fireEvent.click(screen.getByText('Save Anomaly Detection Config'));
  });

  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/settings\/anomaly-prompts$/),
      expect.objectContaining({ method: 'PUT' }),
    );
  });
});

test('renders split rules and saves through the trigger rules endpoint', async () => {
  await act(async () => {
    render(
      <MemoryRouter initialEntries={['/rules']}>
        <SettingsPage forcedTab="rules" hideTabBar pageTitle="Rules" />
      </MemoryRouter>,
    );
  });

  expect(await screen.findByRole('heading', { name: 'Rules', level: 2 })).toBeTruthy();
  expect(screen.queryByRole('tab', { name: 'Rules' })).toBeNull();
  expect(screen.getByText('Detection Rules')).toBeTruthy();
  expect(screen.getByText('Anomaly Detection Rules')).toBeTruthy();
  expect(screen.getByDisplayValue('Bag Watch')).toBeTruthy();
  expect(screen.getByDisplayValue('BAG')).toBeTruthy();
  expect(screen.getByText('Matches detector classes: backpack, handbag, suitcase')).toBeTruthy();

  await act(async () => {
    fireEvent.click(screen.getByText('Save Rules'));
  });

  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/settings\/trigger-rules$/),
      expect.objectContaining({ method: 'PUT' }),
    );
  });

});

test('renders connectors tab and saves both connector subscription types', async () => {
  await act(async () => {
    render(
      <MemoryRouter initialEntries={['/connectors']}>
        <SettingsPage forcedTab="connectors" hideTabBar pageTitle="Connectors" />
      </MemoryRouter>,
    );
  });

  expect(await screen.findByText('Telegram')).toBeTruthy();
  expect(screen.getAllByText('Configured').length).toBeGreaterThan(0);
  expect(screen.queryByRole('tab', { name: 'Connectors' })).toBeNull();
  expect(screen.getByDisplayValue('Ops Chat')).toBeTruthy();
  expect(screen.getAllByDisplayValue('********').length).toBeGreaterThan(0);
  expect(screen.getByDisplayValue('-1001234567890')).toBeTruthy();
  expect(screen.getByDisplayValue('Ops iMessage')).toBeTruthy();
  expect(screen.getByDisplayValue('+15551234567')).toBeTruthy();
  expect(screen.getByDisplayValue('Local Claude Demo')).toBeTruthy();
  expect(screen.getByDisplayValue('http://localhost:8787/v1/messages')).toBeTruthy();
  expect(screen.getByText('Claude-Compatible Anomaly Model')).toBeTruthy();
  expect(screen.getByDisplayValue('http://localhost:8788/v1/messages')).toBeTruthy();
  expect(screen.getByDisplayValue('demo-anomaly-model')).toBeTruthy();
  expect(screen.getByText('Action Connectors')).toBeTruthy();
  expect(screen.getByDisplayValue('Demo Hue')).toBeTruthy();
  expect(screen.getByDisplayValue('http://localhost:8790/actions')).toBeTruthy();

  await act(async () => {
    fireEvent.click(screen.getByText('Save Telegram Subscriptions'));
  });

  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/settings\/telegram-trigger-subscriptions$/),
      expect.objectContaining({ method: 'PUT' }),
    );
  });

  await act(async () => {
    fireEvent.click(screen.getByText('Save Apple Messages Subscriptions'));
  });

  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/settings\/apple-message-trigger-subscriptions$/),
      expect.objectContaining({ method: 'PUT' }),
    );
  });

  await act(async () => {
    fireEvent.click(screen.getByText('Save Third-party API Connectors'));
  });

  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/settings\/claude-api-connectors$/),
      expect.objectContaining({ method: 'PUT' }),
    );
  });

  await act(async () => {
    fireEvent.click(screen.getByText('Save Anomaly Model API'));
  });

  await waitFor(() => {
    const saveCall = global.fetch.mock.calls.find(([url, options]) => (
      url.endsWith('/settings/claude-anomaly-model') && options?.method === 'PUT'
    ));
    expect(saveCall).toBeTruthy();
    const body = JSON.parse(saveCall[1].body);
    expect(body.model_name).toBe('demo-anomaly-model');
    expect(body.base_url).toBe('http://localhost:8788/v1/messages');
  });

  await act(async () => {
    fireEvent.click(screen.getByText('Send Test Anomaly Request'));
  });

  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/settings\/claude-anomaly-model\/test$/),
      expect.objectContaining({ method: 'POST' }),
    );
  });

  await act(async () => {
    fireEvent.click(screen.getByText('Save Action Connectors'));
  });

  await waitFor(() => {
    const saveCall = global.fetch.mock.calls.find(([url, options]) => (
      url.endsWith('/settings/action-connectors') && options?.method === 'PUT'
    ));
    expect(saveCall).toBeTruthy();
    const body = JSON.parse(saveCall[1].body);
    expect(body[0].action_type).toBe('philips_hue');
    expect(body[0].parameters).toEqual({ color: 'red' });
  });
});

test('loads demo trigger presets and serializes selected delivery targets', async () => {
  await act(async () => {
    render(
      <MemoryRouter initialEntries={['/rules']}>
        <SettingsPage forcedTab="rules" hideTabBar pageTitle="Rules" />
      </MemoryRouter>,
    );
  });

  expect(await screen.findByRole('heading', { name: 'Rules', level: 2 })).toBeTruthy();

  await act(async () => {
    fireEvent.click(screen.getByText('Load Demo Presets'));
  });

  expect((await screen.findAllByText('Anomaly Event')).length).toBeGreaterThan(0);
  expect(screen.getAllByText('Unattended Bag').length).toBeGreaterThan(0);
  expect(screen.getAllByText('Loitering Compatibility').length).toBeGreaterThan(0);
  expect(screen.getAllByText('Manual Trigger').length).toBeGreaterThan(0);
  expect(screen.getAllByText('Delivery Targets').length).toBeGreaterThan(0);
  expect(screen.getAllByText('Notification').length).toBeGreaterThan(0);
  expect(screen.getAllByText('Action').length).toBeGreaterThan(0);

  await act(async () => {
    fireEvent.click(screen.getAllByLabelText(/Ops Chat/).at(-1));
    fireEvent.click(screen.getAllByText('Fire Demo Trigger').at(-1));
  });

  await waitFor(() => {
    const fireCall = global.fetch.mock.calls.find(([url, options]) => (
      url.endsWith('/demo/triggers/fire') && options.method === 'POST'
    ));
    expect(fireCall).toBeTruthy();
    const body = JSON.parse(fireCall[1].body);
    expect(body.trigger_key).toBe('manual_trigger');
    expect(body.delivery_target_ids).toEqual([61, 71]);
  });
});

test('renders model library with readable stage and model descriptions', async () => {
  await act(async () => {
    render(
      <MemoryRouter initialEntries={['/settings?tab=model-library']}>
        <SettingsPage />
      </MemoryRouter>,
    );
  });

  expect((await screen.findAllByText('Model Inventory')).length).toBeGreaterThan(0);
  expect(screen.getAllByText('Model Inventory').length).toBeGreaterThan(0);
  expect(screen.getByText('Mount Models')).toBeTruthy();
  fireEvent.click(screen.getAllByRole('button', { name: 'Model Library' }).at(-1));
  expect(screen.getAllByText('Detector Models').length).toBeGreaterThan(0);
  expect(screen.getByText('YOLOX Small (GPU)')).toBeTruthy();
  expect(screen.getAllByText('Mounted').length).toBeGreaterThan(0);
  expect(screen.getAllByText('Default').length).toBeGreaterThan(0);
  expect(screen.getAllByText(/find people and bags in each frame/i).length).toBeGreaterThan(0);
  expect(
    screen.getAllByText(/Available detector classes include person, bicycle, car, backpack, handbag, suitcase/i).length
  ).toBeGreaterThan(0);
  expect(screen.getAllByText(/Prompt Rules Stage 2/).length).toBeGreaterThan(0);
  expect(screen.queryByText('Person ReID Models')).toBeNull();
  expect(screen.getByText(/GET .*\/model-options/)).toBeTruthy();
});

test('renders appearance settings and saves workspace theme selection', async () => {
  const onSaveAppearance = jest.fn(() => Promise.resolve('fidelity-dark'));

  await act(async () => {
    render(
      <MemoryRouter initialEntries={['/settings?tab=appearance']}>
        <SettingsPage
          themeOptions={[
            {
              key: 'fidelity-light',
              label: 'Fidelity Light',
              description: 'Professional teal light mode.',
              group: 'light',
              swatches: ['#557e85'],
            },
            {
              key: 'fidelity-dark',
              label: 'Fidelity Dark',
              description: 'Dark professional mode.',
              group: 'dark',
              swatches: ['#78a3aa'],
            },
          ]}
          currentThemeKey="fidelity-light"
          appearanceLoaded
          onSaveAppearance={onSaveAppearance}
        />
      </MemoryRouter>,
    );
  });

  expect(await screen.findByText('Workspace Theme')).toBeTruthy();
  expect(screen.getByText('Fidelity Light')).toBeTruthy();
  expect(screen.getByText('Fidelity Dark')).toBeTruthy();

  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: /fidelity dark/i }));
  });

  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Save Appearance' }));
  });

  expect(onSaveAppearance).toHaveBeenCalledWith('fidelity-dark');
  expect(await screen.findByText('Theme updated to Fidelity Dark.')).toBeTruthy();
});

test('shows a helpful tip when no saved sources exist for alert rules', async () => {
  global.fetch = jest.fn((url, options = {}) => {
    if (url.endsWith('/settings/input-sources') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse([]);
    }
    if (url.endsWith('/model-options')) {
      return buildJsonResponse({ model_zoo: { catalog_available: true }, stages: [] });
    }
    if (url.endsWith('/model-bindings') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse([]);
    }
    if (url.endsWith('/settings/anomaly-prompts/standard')) {
      return buildJsonResponse({
        anomaly_items: [
          { item: 'weapon' },
        ],
        anomaly_behaviors: ['running'],
      });
    }
    if (url.endsWith('/settings/appearance') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse({
        theme_key: 'fidelity-light',
      });
    }
    if (url.endsWith('/settings/anomaly-prompts') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse({
        anomaly_items: [
          { item: 'weapon' },
        ],
        anomaly_behaviors: ['running'],
      });
    }
    if (url.endsWith('/settings/trigger-rules') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse([]);
    }
    if (url.endsWith('/settings/alert-rules') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse([]);
    }
    if (url.endsWith('/settings/alert-rule-options') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse({ sources: [] });
    }
    if (url.endsWith('/settings/telegram-trigger-subscriptions') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse([]);
    }
    if (url.endsWith('/settings/apple-message-trigger-subscriptions') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse([]);
    }
    if (url.endsWith('/settings/claude-api-connectors') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse([]);
    }
    if (url.endsWith('/settings/claude-anomaly-model') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse({
        enabled: false,
        base_url: '',
        auth_token: '',
        model_name: 'claude-compatible-anomaly',
        timeout_seconds: 10,
        retry_count: 1,
        prompt_template: '',
      });
    }
    if (url.endsWith('/settings/action-connectors') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse([]);
    }
    return buildJsonResponse({});
  });

  await act(async () => {
    render(
      <MemoryRouter initialEntries={['/rules']}>
        <SettingsPage forcedTab="rules" hideTabBar pageTitle="Rules" />
      </MemoryRouter>,
    );
  });

  expect(await screen.findByText('Please connect and save a source first in the Sources tab.')).toBeTruthy();
});
