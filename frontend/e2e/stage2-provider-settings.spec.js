const { test, expect } = require('@playwright/test');

const buildModelOptions = () => ({
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
    anomaly_stage_2: ['chatgpt_api_stage_2', 'lm_studio_stage_2'],
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
            classes: ['person', 'backpack'],
          },
        },
      ],
    },
    {
      stage: 'tracker',
      options: [
        {
          model_key: 'builtin_bytetrack',
          display_name: 'ByteTrack',
          stage: 'tracker',
          adapter: 'bytetrack_tracker',
          is_mounted: true,
        },
      ],
    },
    {
      stage: 'anomaly_stage_1',
      options: [
        {
          model_key: 'heuristic_presence_stage_1',
          display_name: 'Heuristic Presence Stage 1',
          stage: 'anomaly_stage_1',
          adapter: 'heuristic_presence_stage_1',
          is_mounted: true,
        },
      ],
    },
    {
      stage: 'anomaly_stage_2',
      options: [
        {
          model_key: 'chatgpt_api_stage_2',
          display_name: 'OpenAI Stage 2',
          stage: 'anomaly_stage_2',
          adapter: 'openai_compatible_stage_2',
          is_mounted: true,
          runtime: { provider: 'openai' },
        },
        {
          model_key: 'lm_studio_stage_2',
          display_name: 'LM Studio Stage 2',
          stage: 'anomaly_stage_2',
          adapter: 'openai_compatible_stage_2',
          is_mounted: true,
          runtime: { provider: 'lm_studio' },
        },
      ],
    },
  ],
});

const buildStage2Providers = () => ([
  {
    provider_key: 'openai',
    display_name: 'OpenAI',
    enabled: true,
    base_url: 'https://api.openai.com/v1',
    model_name: 'gpt-5.4-mini',
    timeout_seconds: 30,
    auth_optional: false,
    api_key: '********',
    auth_token: '',
    secret_present: true,
    last_test_status: 'ok',
    last_test_message: 'Connection test succeeded.',
    last_tested_at: '2026-06-05T12:00:00Z',
  },
  {
    provider_key: 'lm_studio',
    display_name: 'LM Studio',
    enabled: false,
    base_url: 'http://localhost:1234/v1',
    model_name: 'qwen-local',
    timeout_seconds: 30,
    auth_optional: true,
    api_key: '',
    auth_token: '',
    secret_present: false,
    last_test_status: null,
    last_test_message: null,
    last_tested_at: null,
  },
  {
    provider_key: 'lauretta',
    display_name: 'Lauretta',
    enabled: false,
    base_url: 'https://lauretta.example/v1',
    model_name: 'lauretta-anomaly-stage-2',
    timeout_seconds: 30,
    auth_optional: false,
    api_key: '',
    auth_token: '',
    secret_present: false,
    last_test_status: null,
    last_test_message: null,
    last_tested_at: null,
  },
  {
    provider_key: 'claude_compatible',
    display_name: 'Claude-Compatible',
    enabled: false,
    base_url: 'https://claude.example/v1',
    model_name: 'claude-compatible-anomaly',
    timeout_seconds: 30,
    auth_optional: false,
    api_key: '',
    auth_token: '',
    secret_present: false,
    last_test_status: null,
    last_test_message: null,
    last_tested_at: null,
  },
]);

test.beforeEach(async ({ page }) => {
  let stage2Providers = buildStage2Providers();
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    const json = async (body, status = 200) => {
      await route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(body),
      });
    };

    if (path.endsWith('/settings/input-sources') && method === 'GET') {
      return json([
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
          anomaly_stage_1_model_key: null,
          anomaly_stage_2_model_key: null,
        },
      ]);
    }
    if (path.endsWith('/settings/appearance') && method === 'GET') {
      return json({ theme_key: 'fidelity-light' });
    }
    if (path.endsWith('/model-options') && method === 'GET') {
      return json(buildModelOptions());
    }
    if (path.endsWith('/model-bindings') && method === 'GET') {
      return json([
        { stage: 'detector', model_key: 'builtin_yolox_s_gpu', binding_scope: 'default', source_id: null },
        { stage: 'tracker', model_key: 'builtin_bytetrack', binding_scope: 'default', source_id: null },
        { stage: 'anomaly_stage_1', model_key: 'heuristic_presence_stage_1', binding_scope: 'default', source_id: null },
        { stage: 'anomaly_stage_2', model_key: 'chatgpt_api_stage_2', binding_scope: 'default', source_id: null },
      ]);
    }
    if (path.endsWith('/settings/anomaly-prompts') && method === 'GET') {
      return json({
        anomaly_items: [{ item: 'weapon' }],
        anomaly_behaviors: ['running'],
      });
    }
    if (path.endsWith('/settings/stage2-provider-settings') && method === 'GET') {
      return json(stage2Providers);
    }
    if (path.endsWith('/settings/trigger-rules') && method === 'GET') {
      return json([]);
    }
    if (path.endsWith('/settings/alert-rules') && method === 'GET') {
      return json([]);
    }
    if (path.endsWith('/settings/alert-rule-options') && method === 'GET') {
      return json({ sources: [] });
    }
    if (path.endsWith('/settings/telegram-trigger-subscriptions') && method === 'GET') {
      return json([]);
    }
    if (path.endsWith('/settings/apple-message-trigger-subscriptions') && method === 'GET') {
      return json([]);
    }
    if (path.endsWith('/settings/govee-connector-endpoints') && method === 'GET') {
      return json([]);
    }
    if (path.endsWith('/settings/connector-endpoints') && method === 'GET') {
      return json([]);
    }
    if (path.endsWith('/trigger-zoo') && method === 'GET') {
      return json([]);
    }
    if (path.endsWith('/connector-zoo') && method === 'GET') {
      return json([]);
    }
    if (path.endsWith('/settings/connector-zoo-repo') && method === 'GET') {
      return json({
        catalog_url: 'https://raw.githubusercontent.com/lauretta-io/hearthlight/main/shared/catalogs/connector_zoo_repo.yaml',
      });
    }
    if (path.endsWith('/connector-zoo/repo') && method === 'GET') {
      return json({
        catalog_url: 'https://raw.githubusercontent.com/lauretta-io/hearthlight/main/shared/catalogs/connector_zoo_repo.yaml',
        source_url: 'https://raw.githubusercontent.com/lauretta-io/hearthlight/main/shared/catalogs/connector_zoo_repo.yaml',
        generated_at: '2026-06-05T12:00:00Z',
        last_refreshed_at: '2026-06-05T12:00:00Z',
        error: null,
        from_cache: false,
        connectors: [],
      });
    }
    if (path.endsWith('/settings/stage2-provider-settings') && method === 'PUT') {
      const payload = JSON.parse(request.postData() || '[]');
      stage2Providers = payload.map((item) => ({
        ...item,
        api_key: item.api_key ? '********' : '',
        auth_token: item.auth_token ? '********' : '',
        secret_present: Boolean(item.api_key || item.auth_token || item.provider_key === 'openai'),
        last_test_status: item.last_test_status ?? null,
        last_test_message: item.last_test_message ?? null,
        last_tested_at: item.last_tested_at ?? null,
      }));
      return json(stage2Providers);
    }
    if (path.endsWith('/settings/stage2-provider-settings/test') && method === 'POST') {
      const payload = JSON.parse(request.postData() || '{}');
      if (payload.provider_key === 'lm_studio' && payload.base_url === 'http://offline.local/v1') {
        return json({ detail: 'Connection timed out while contacting the provider.' }, 502);
      }
      return json({
        provider_key: payload.provider_key,
        ok: true,
        detail: 'Connection test succeeded.',
        effective_base_url: payload.base_url,
        effective_model_name: payload.model_name,
        secret_present: Boolean(payload.api_key || payload.auth_token || payload.provider_key === 'openai'),
        last_test_status: 'ok',
        last_tested_at: '2026-06-05T12:05:00Z',
      });
    }

    return json({});
  });
});

test('loads, saves, and preserves masked OpenAI provider settings', async ({ page }) => {
  await page.goto('/settings?tab=sources');

  const openaiBaseUrl = page.locator('input[value="https://api.openai.com/v1"]').first();
  const maskedSecret = page.locator('input[type="password"][value="********"]').first();

  await expect(page.getByRole('heading', { name: 'Stage 2 Provider Settings' })).toBeVisible();
  await expect(page.getByText('Current Stage 2 Binding')).toBeVisible();
  await expect(openaiBaseUrl).toBeVisible();
  await expect(maskedSecret).toBeVisible();

  await openaiBaseUrl.fill('https://api.openai.com/v2');
  await page.getByRole('button', { name: 'Save Stage 2 Provider Settings' }).click();

  await expect(page.locator('.banner').filter({ hasText: 'Stage 2 provider settings saved.' }).first()).toBeVisible();
  await expect(page.locator('input[value="https://api.openai.com/v2"]').first()).toBeVisible();
  await expect(page.locator('input[type="password"][value="********"]').first()).toBeVisible();
});

test('validates required OpenAI secrets and omits raw secrets from browser storage', async ({ page }) => {
  await page.goto('/settings?tab=sources');

  await expect(page.getByRole('heading', { name: 'Stage 2 Provider Settings' })).toBeVisible();
  await page.locator('input[type="password"][value="********"]').first().fill('');
  await page.getByRole('button', { name: 'Save Stage 2 Provider Settings' }).click();

  await expect(page.getByText('API Key is required when the provider is enabled.')).toBeVisible();

  const storageSnapshot = await page.evaluate(() => ({
    local: Object.values(localStorage),
    session: Object.values(sessionStorage),
    html: document.body.innerHTML,
  }));
  expect(storageSnapshot.local.join(' ')).not.toContain('sk-');
  expect(storageSnapshot.session.join(' ')).not.toContain('sk-');
  expect(storageSnapshot.html).not.toContain('sk-');
});

test('supports LM Studio optional auth and surfaces connectivity failures', async ({ page }) => {
  await page.goto('/settings?tab=sources');

  await expect(page.getByRole('heading', { name: 'Stage 2 Provider Settings' })).toBeVisible();
  await page.locator('input[value="http://localhost:1234/v1"]').first().fill('http://offline.local/v1');
  await page.getByRole('button', { name: 'Test Connection' }).nth(1).click();

  await expect(page.locator('.banner').filter({ hasText: 'Connection timed out while contacting the provider.' }).first()).toBeVisible();
});
