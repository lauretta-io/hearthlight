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
    if (url.endsWith('/settings/govee-connector-endpoints') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse([]);
    }
    if (url.endsWith('/trigger-zoo')) {
      return buildJsonResponse([]);
    }
    if (url.endsWith('/connector-zoo')) {
      return buildJsonResponse([
        {
          key: 'telegram',
          label: 'Telegram',
          description: 'Telegram connector',
          category: 'messaging',
          enabled: true,
        },
        {
          key: 'govee',
          label: 'Govee Light Connection',
          description: 'Optional Govee light connector plugin.',
          category: 'integrations',
          enabled: true,
          plugin_key: 'govee_light_connection',
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
    if (url.includes('/settings/govee/test') && options.method === 'POST') {
      return buildJsonResponse({
        valid: true,
        device_count: 1,
        light_device_count: 1,
        message: 'Govee API key is valid.',
      });
    }
    if (url.includes('/settings/govee/devices') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse([
        {
          sku: 'H6000',
          device: 'AA:BB:CC:DD',
          device_name: 'Desk Light',
          device_type: 'devices.types.light',
          capability_options: [
            {
              key: 'devices.capabilities.on_off:powerSwitch',
              label: 'Power',
              capability_type: 'devices.capabilities.on_off',
              instance: 'powerSwitch',
              input_kind: 'enum',
              values: [
                { label: 'on', value: 1 },
                { label: 'off', value: 0 },
              ],
              default_value: 1,
            },
          ],
        },
      ]);
    }
    if (url.endsWith('/settings/govee-connector-endpoints') && options.method === 'PUT') {
      const payload = JSON.parse(options.body);
      return buildJsonResponse(payload.map((item, index) => ({
        id: 71 + index,
        connector_key: 'govee',
        label: item.label,
        enabled: item.enabled,
        config: item.config,
        delivery_capabilities: item.delivery_capabilities,
      })));
    }
    if (url.includes('/settings/govee-connector-endpoints/test') && options.method === 'POST') {
      return buildJsonResponse({
        detail: 'Govee trigger action sent.',
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
  expect(screen.getByText('Govee Light Connection')).toBeTruthy();
  expect(screen.getAllByText('Configured').length).toBeGreaterThan(0);
  expect(screen.queryByRole('tab', { name: 'Connectors' })).toBeNull();
  expect(screen.getByDisplayValue('Ops Chat')).toBeTruthy();
  expect(screen.getByDisplayValue('********')).toBeTruthy();
  expect(screen.getByDisplayValue('-1001234567890')).toBeTruthy();
  expect(screen.getByDisplayValue('Ops iMessage')).toBeTruthy();
  expect(screen.getByDisplayValue('+15551234567')).toBeTruthy();

  await act(async () => {
    fireEvent.change(screen.getByPlaceholderText('123456:ABC...'), {
      target: { value: '123456:replacement-token' },
    });
  });

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
    fireEvent.click(screen.getAllByText('Add Connection')[0]);
  });
  expect(screen.getByPlaceholderText('Govee API key')).toBeTruthy();

  await act(async () => {
    fireEvent.change(screen.getByPlaceholderText('Govee API key'), {
      target: { value: 'test-govee-key' },
    });
  });

  await act(async () => {
    fireEvent.click(screen.getByText('Discover Devices'));
  });

  expect((await screen.findAllByText(/Discovered 1 Govee light device/)).length).toBeGreaterThan(0);

  await act(async () => {
    fireEvent.change(screen.getByLabelText('Device'), {
      target: { value: 'H6000:AA:BB:CC:DD' },
    });
  });

  await act(async () => {
    fireEvent.click(screen.getByText('Save Govee Light Connections'));
  });

  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/settings\/govee-connector-endpoints$/),
      expect.objectContaining({ method: 'PUT' }),
    );
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
