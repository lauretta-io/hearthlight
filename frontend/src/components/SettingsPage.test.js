import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SettingsPage from './SettingsPage';

const buildJsonResponse = (body) =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve(body),
  });

const buildErrorResponse = (status, body) =>
  Promise.resolve({
    ok: false,
    status,
    json: () => Promise.resolve(body),
  });

beforeEach(() => {
  let connectorZooRepoSettings = {
    catalog_url: 'https://raw.githubusercontent.com/lauretta-io/hearthlight/main/shared/catalogs/connector_zoo_repo.yaml',
  };
  let repoConnectorZooCatalog = {
    catalog_url: connectorZooRepoSettings.catalog_url,
    source_url: connectorZooRepoSettings.catalog_url,
    generated_at: '2026-05-27T00:00:00Z',
    last_refreshed_at: '2026-05-27T00:00:00Z',
    error: null,
    from_cache: false,
    connectors: [
      {
        key: 'govee',
        label: 'Govee Light Connection',
        description: 'Optional Govee light connector plugin.',
        category: 'integrations',
        enabled: true,
        plugin_key: 'govee_light_connection',
        plugin_version: '0.8.1',
        source_url: 'file:///workspace/shared/plugins/govee_light_connection/',
        installed: false,
      },
    ],
  };
  let goveeEndpoints = [];
  let genericConnectorEndpoints = [];
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
          frame_processing_mode: 'frame_skip',
          process_every_n_frames: 1,
          target_frame_rate: null,
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
          delivery_target_ids: [41],
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
          delivery_target_ids: [41],
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
      return buildJsonResponse(goveeEndpoints);
    }
    if (url.endsWith('/settings/connector-endpoints') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse(genericConnectorEndpoints);
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
      ]);
    }
    if (url.endsWith('/settings/connector-zoo-repo') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse(connectorZooRepoSettings);
    }
    if (url.endsWith('/connector-zoo/repo') && (!options.method || options.method === 'GET')) {
      return buildJsonResponse(repoConnectorZooCatalog);
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
          delivery_target_ids: [41],
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
          delivery_target_ids: [41],
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
      goveeEndpoints = payload.map((item, index) => ({
        id: 71 + index,
        connector_key: 'govee',
        label: item.label,
        enabled: item.enabled,
        config: item.config,
        delivery_capabilities: item.delivery_capabilities,
      }));
      return buildJsonResponse(goveeEndpoints);
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
    if (url.endsWith('/settings/connector-zoo-repo') && options.method === 'PUT') {
      connectorZooRepoSettings = JSON.parse(options.body);
      repoConnectorZooCatalog = {
        ...repoConnectorZooCatalog,
        catalog_url: connectorZooRepoSettings.catalog_url,
        source_url: connectorZooRepoSettings.catalog_url,
      };
      return buildJsonResponse(connectorZooRepoSettings);
    }
    if (url.endsWith('/connector-zoo/repo/install') && options.method === 'POST') {
      const payload = JSON.parse(options.body);
      repoConnectorZooCatalog = {
        ...repoConnectorZooCatalog,
        connectors: repoConnectorZooCatalog.connectors.map((entry) =>
          entry.key === payload.connector_key ? { ...entry, installed: true } : entry
        ),
      };
      genericConnectorEndpoints = [
        {
          id: 81,
          connector_key: payload.connector_key,
          label: 'Govee Light Connection',
          enabled: true,
          config: {},
          delivery_capabilities: ['light_control'],
          resolved: false,
          unavailable_reason: 'connector plugin component govee is unavailable',
        },
      ];
      goveeEndpoints = [
        {
          id: 82,
          connector_key: 'govee',
          label: 'Govee Light Connection',
          enabled: true,
          config: {
            api_key: '',
            sku: '',
            device: '',
            device_name: '',
            capability_key: '',
            capability_type: '',
            capability_instance: '',
            capability_value: '',
            capability_value_label: '',
          },
          delivery_capabilities: ['light_control'],
          resolved: false,
          unavailable_reason: 'connector plugin component govee is unavailable',
        },
      ];
      return buildJsonResponse({
        connector_key: payload.connector_key,
        plugin_key: 'govee_light_connection',
        connector_endpoint_id: 82,
        restart_required: true,
        message: 'Govee Light Connection was added. Restart Hearthlight to activate the plugin runtime.',
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
  expect(screen.getByText('Type')).toBeTruthy();
  expect(screen.getByText('Camera URL')).toBeTruthy();
  expect(screen.getByText('Frame Processing')).toBeTruthy();
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

test('keeps source overrides visible and exposes target frame rate mode', async () => {
  await act(async () => {
    render(
      <MemoryRouter initialEntries={['/settings?tab=sources']}>
        <SettingsPage />
      </MemoryRouter>,
    );
  });

  expect(await screen.findByDisplayValue('Gate 1')).toBeTruthy();
  expect(screen.getByText('Detector Override')).toBeTruthy();

  fireEvent.change(screen.getByDisplayValue('Select Frame Skip'), {
    target: { value: 'target_frame_rate' },
  });

  await waitFor(() => {
    expect(screen.getByText('Target Frame Rate')).toBeTruthy();
  });
  expect(screen.getByText('Detector Override')).toBeTruthy();
});

test('limits run model bindings to mounted models only', async () => {
  await act(async () => {
    render(
      <MemoryRouter initialEntries={['/settings?tab=sources']}>
        <SettingsPage />
      </MemoryRouter>,
    );
  });

  expect(await screen.findByText('Default Model Bindings')).toBeTruthy();

  const detectorOverrideSelect = screen.getByLabelText('Detector Override');
  const detectorOverrideLabels = Array.from(detectorOverrideSelect.querySelectorAll('option')).map((option) => option.textContent);
  expect(detectorOverrideLabels).toContain('YOLOX Small (GPU)');
  expect(detectorOverrideLabels).not.toContain('YOLOX Tiny (CPU)');

  const defaultDetectorSelect = screen.getByLabelText('Detector');
  const defaultDetectorLabels = Array.from(defaultDetectorSelect.querySelectorAll('option')).map((option) => option.textContent);
  expect(defaultDetectorLabels).toContain('YOLOX Small (GPU)');
  expect(defaultDetectorLabels).not.toContain('YOLOX Tiny (CPU)');
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
  expect(screen.getByText('Bag Watch')).toBeTruthy();
  expect(screen.getByText('Ops Chat')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Edit' })).toBeTruthy();

  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
  });

  expect(screen.getByDisplayValue('Bag Watch')).toBeTruthy();
  expect(screen.getByDisplayValue('BAG')).toBeTruthy();
  expect(screen.getByText('Matches detector classes: backpack, handbag, suitcase')).toBeTruthy();
  expect(screen.getByText('Connectors To Activate')).toBeTruthy();
  expect(screen.getByText(/Ops Chat/)).toBeTruthy();

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

test('auto-selects the first anomaly target when a new anomaly rule has valid options', async () => {
  await act(async () => {
    render(
      <MemoryRouter initialEntries={['/rules']}>
        <SettingsPage forcedTab="rules" hideTabBar pageTitle="Rules" />
      </MemoryRouter>,
    );
  });

  expect(await screen.findByRole('heading', { name: 'Rules', level: 2 })).toBeTruthy();

  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Add Anomaly Rule' }));
  });

  const sourceCheckbox = screen.getByRole('checkbox', { name: /Gate 1/i });
  await act(async () => {
    fireEvent.click(sourceCheckbox);
  });

  await waitFor(() => {
    expect(screen.getByDisplayValue('weapon')).toBeTruthy();
  });

  const anomalyTypeSelect = screen.getByDisplayValue('Object');
  await act(async () => {
    fireEvent.change(anomalyTypeSelect, { target: { value: 'behavior' } });
  });

  await waitFor(() => {
    expect(screen.getByDisplayValue('running')).toBeTruthy();
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
    fireEvent.click(screen.getByRole('button', { name: 'Connector Zoo' }));
  });

  expect(await screen.findByText('Available Connectors')).toBeTruthy();
  expect(screen.getByDisplayValue('https://raw.githubusercontent.com/lauretta-io/hearthlight/main/shared/catalogs/connector_zoo_repo.yaml')).toBeTruthy();
  expect(screen.getByText('Govee Light Connection')).toBeTruthy();

  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Add to System' }));
  });

  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/connector-zoo\/repo\/install$/),
      expect.objectContaining({ method: 'POST' }),
    );
  });

  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Connections' }));
  });

  expect(await screen.findByText('Govee Light Connection')).toBeTruthy();
  expect(screen.getByText(/restart hearthlight to activate the plugin runtime/i)).toBeTruthy();
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
  expect(screen.getAllByText('YOLOX Small (GPU)').length).toBeGreaterThan(0);
  expect(screen.getAllByText('Mounted').length).toBeGreaterThan(0);
  expect(screen.getAllByText('Default').length).toBeGreaterThan(0);
  expect(screen.getAllByText(/find people and bags in each frame/i).length).toBeGreaterThan(0);
  expect(
    screen.getAllByText(/Available detector classes include person, bicycle, car, backpack, handbag, suitcase/i).length
  ).toBeGreaterThan(0);
  expect(screen.getAllByText(/Prompt Rules Stage 2/).length).toBeGreaterThan(0);
  expect(screen.queryByText('Person ReID Models')).toBeNull();
  expect(screen.getAllByText(/GET .*\/model-options/).length).toBeGreaterThan(0);
});

test('confirms before forcibly unmounting models that are still in use', async () => {
  const baseFetch = global.fetch;
  global.fetch = jest.fn((url, options = {}) => {
    if (url.includes('/mounted-models') && options.method === 'PUT') {
      if (url.includes('force=true')) {
        return buildJsonResponse([
          { stage: 'detector', mounted_model_keys: [] },
          { stage: 'tracker', mounted_model_keys: ['builtin_bytetrack'] },
          { stage: 'anomaly_stage_1', mounted_model_keys: ['heuristic_presence_stage_1'] },
          { stage: 'anomaly_stage_2', mounted_model_keys: ['prompt_rules_stage_2'] },
        ]);
      }
      return buildErrorResponse(409, {
        detail: {
          message: 'cannot unmount models currently in use: detector: builtin_yolox_s_gpu',
          requires_force: true,
          active_run: true,
          in_use_models: {
            detector: ['builtin_yolox_s_gpu'],
          },
        },
      });
    }
    return baseFetch(url, options);
  });

  await act(async () => {
    render(
      <MemoryRouter initialEntries={['/settings?tab=model-library']}>
        <SettingsPage />
      </MemoryRouter>,
    );
  });

  await screen.findAllByText('Model Inventory');
  await act(async () => {
    fireEvent.click(screen.getByRole('checkbox', { name: /YOLOX Small \(GPU\) · Mounted/i }));
  });
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Remount Models' }));
  });

  expect(await screen.findByRole('dialog')).toBeTruthy();
  expect(screen.getByText('Models Currently In Use')).toBeTruthy();
  expect(screen.getByText(/stop the current run and clear any bindings/i)).toBeTruthy();

  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Stop and Remove Models' }));
  });

  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/mounted-models?force=true'),
      expect.objectContaining({ method: 'PUT' }),
    );
  });
  expect((await screen.findAllByText('Mounted model inventory updated.')).length).toBeGreaterThan(0);
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
