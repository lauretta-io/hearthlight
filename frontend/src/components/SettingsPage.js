import React, { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { BaseURL } from '../config';
import {
  fetchJson,
  fetchWithTimeout,
  formatApiError,
  parseApiJson,
  readApiPayload,
} from '../utils/api';
import MonitoringPage from './MonitoringPage';
import {
  formatUploadedVideoSummary,
  SUPPORTED_VIDEO_LABEL,
  validateSelectedVideoFile,
  VIDEO_UPLOAD_ACCEPT,
} from '../utils/videoUpload';
import { THEME_GROUP_LABELS, getThemeOption } from '../theme';
import {
  SOURCES_UPDATED_EVENT,
  dispatchRunStarted,
  isStartBlockedMessage,
} from '../utils/runLifecycle';
import '../styles/CameraConfig.css';

const TASK_OPTIONS = ['PERSON', 'BAG'];
const SOURCE_KIND_OPTIONS = [
  { value: 'camera_url', label: 'Camera URL' },
  { value: 'video_upload', label: 'Uploaded Video' },
  { value: 'webcam', label: 'Webcam' },
];
const MODEL_STAGE_OPTIONS = [
  { stage: 'detector', label: 'Detector', field: 'detector_model_key' },
  { stage: 'tracker', label: 'Tracker', field: 'tracker_model_key' },
  { stage: 'anomaly_stage_1', label: 'Heuristic Filter', field: 'anomaly_stage_1_model_key' },
  { stage: 'anomaly_stage_2', label: 'Anomaly Detection', field: 'anomaly_stage_2_model_key' },
];
const TEMPLATE_OPTIONS = ['active', 'example', 'master_config', 'office_config'];
const ALERT_SIGNAL_FAMILY_OPTIONS = [
  { value: 'detector', label: 'Detector' },
  { value: 'anomaly_object', label: 'Anomaly Object' },
  { value: 'anomaly_activity', label: 'Anomaly Activity' },
];
const RULE_KIND_OPTIONS = [
  { value: 'detector', label: 'Detection Rules' },
  { value: 'anomaly', label: 'Anomaly Detection Rules' },
];
const ANOMALY_TARGET_KIND_OPTIONS = [
  { value: 'object', label: 'Object' },
  { value: 'behavior', label: 'Behavior' },
];
const ALERT_LEVEL_OPTIONS = [
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
];
const MODEL_LIBRARY_SUB_TABS = [
  { key: 'inventory', label: 'Model Inventory' },
  { key: 'library', label: 'Model Library' },
];
const CONNECTOR_SUB_TABS = [
  { key: 'connections', label: 'Connections' },
  { key: 'connector-zoo', label: 'Connector Zoo' },
];
const FRAME_PROCESSING_MODE_OPTIONS = [
  { value: 'frame_skip', label: 'Select Frame Skip' },
  { value: 'target_frame_rate', label: 'Set Target Frame Rate' },
];
const EMPTY_PROMPT_SETTINGS = {
  anomaly_items: [],
  anomaly_behaviors: [],
};
const STAGE2_PROVIDER_OPTIONS = [
  {
    provider_key: 'openai',
    label: 'OpenAI',
    secretField: 'api_key',
    secretLabel: 'API Key',
    authOptional: false,
    runtimeProviders: ['openai'],
  },
  {
    provider_key: 'lm_studio',
    label: 'LM Studio',
    secretField: 'api_key',
    secretLabel: 'API Key',
    authOptional: true,
    runtimeProviders: ['lm_studio'],
  },
  {
    provider_key: 'lauretta',
    label: 'Lauretta',
    secretField: 'api_key',
    secretLabel: 'API Key',
    authOptional: false,
    runtimeProviders: ['lauretta'],
  },
  {
    provider_key: 'claude_compatible',
    label: 'Claude-Compatible',
    secretField: 'auth_token',
    secretLabel: 'Auth Token',
    authOptional: false,
    runtimeProviders: ['claude_compatible', 'anthropic'],
  },
];
const SETTINGS_TABS = [
  { key: 'monitoring', label: 'Monitor Run' },
  { key: 'sources', label: 'Sources' },
  { key: 'model-library', label: 'Model Library' },
  { key: 'appearance', label: 'Appearance' },
  { key: 'initialization', label: 'Initialization' },
];
const STANDALONE_PAGE_TABS = [
  { key: 'rules', label: 'Rules' },
  { key: 'connectors', label: 'Connectors' },
];
const MODEL_STAGE_COPY = {
  detector: {
    title: 'Detector Models',
    description: 'These models look at each frame and find the people and bags that the rest of the pipeline will follow.',
    usedFor: 'Spotting people and bags in raw video frames.',
  },
  tracker: {
    title: 'Tracker Models',
    description: 'These models keep detections linked over time so the system can follow the same person or bag across frames.',
    usedFor: 'Turning frame-by-frame detections into stable moving tracks.',
  },
  anomaly_stage_1: {
    title: 'Heuristic Filter Models',
    description: 'These models run the first AI anomaly pass and decide which moments are worth escalating for deeper reasoning.',
    usedFor: 'AI-backed anomaly screening and event prefiltering.',
  },
  anomaly_stage_2: {
    title: 'Anomaly Detection Models',
    description: 'These models interpret Stage 1 events using the saved anomaly prompt configuration and final anomaly labels.',
    usedFor: 'Prompt-driven anomaly interpretation and event labeling.',
  },
};

const normalizeBindingsPayload = (payload) => {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.bindings)) return payload.bindings;
  if (Array.isArray(payload?.items)) return payload.items;
  return [];
};

const extractDefaultBindings = (bindingPayload, modelPayload) => {
  const nextDefaults = {};
  normalizeBindingsPayload(bindingPayload)
    .filter((binding) => binding.binding_scope === 'default')
    .forEach((binding) => {
      if (binding.model_key) {
        nextDefaults[binding.stage] = binding.model_key;
      }
    });

  const catalogDefaults = modelPayload?.default_bindings;
  if (catalogDefaults && typeof catalogDefaults === 'object') {
    MODEL_STAGE_OPTIONS.forEach((option) => {
      const modelKey = catalogDefaults[option.stage];
      if (modelKey && !nextDefaults[option.stage]) {
        nextDefaults[option.stage] = modelKey;
      }
    });
  }

  const mounted = modelPayload?.mounted_models || {};
  MODEL_STAGE_OPTIONS.forEach((option) => {
    if (nextDefaults[option.stage]) {
      return;
    }
    const mountedKeys = mounted[option.stage];
    if (Array.isArray(mountedKeys) && mountedKeys[0]) {
      nextDefaults[option.stage] = mountedKeys[0];
    }
  });

  (modelPayload?.stages || []).forEach((stageEntry) => {
    const stage = stageEntry?.stage;
    if (!stage || nextDefaults[stage]) {
      return;
    }
    const options = Array.isArray(stageEntry.options) ? stageEntry.options : [];
    const preferred = options.find((option) => option.is_mounted) || options[0];
    if (preferred?.model_key) {
      nextDefaults[stage] = preferred.model_key;
    }
  });

  return nextDefaults;
};

const resolveEffectiveDefaultKey = (
  stage,
  defaultBindings,
  modelOptionCatalog,
  mountedModelsByStage,
) => (
  defaultBindings?.[stage]
  || modelOptionCatalog?.default_bindings?.[stage]
  || mountedModelsByStage?.[stage]?.[0]
  || ''
);

const MODEL_OPTIONS_FETCH_TIMEOUT_MS = 60000;

const normalizeListPayload = (payload) => {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.items)) return payload.items;
  return [];
};

const normalizeRepoConnectorZooPayload = (payload) => ({
  catalog_url: payload?.catalog_url ?? '',
  source_url: payload?.source_url ?? '',
  generated_at: payload?.generated_at ?? null,
  last_refreshed_at: payload?.last_refreshed_at ?? null,
  error: payload?.error ?? null,
  from_cache: Boolean(payload?.from_cache),
  connectors: Array.isArray(payload?.connectors) ? payload.connectors : [],
});

const resolveApiErrorMessage = (payload, fallbackMessage) => {
  if (typeof payload?.detail === 'string' && payload.detail.trim()) {
    return payload.detail;
  }
  if (typeof payload?.detail?.message === 'string' && payload.detail.message.trim()) {
    return payload.detail.message;
  }
  if (typeof payload?.message === 'string' && payload.message.trim()) {
    return payload.message;
  }
  return fallbackMessage;
};

const normalizeMountedModelConflict = (payload) => {
  const detail = payload?.detail;
  if (!detail || typeof detail !== 'object' || !detail.requires_force) {
    return null;
  }
  return {
    message: resolveApiErrorMessage(payload, 'Mounted models are currently in use.'),
    active_run: Boolean(detail.active_run),
    in_use_models: detail.in_use_models && typeof detail.in_use_models === 'object'
      ? detail.in_use_models
      : {},
  };
};

const createSourceDraft = (kind = 'camera_url') => ({
  clientKey: `settings-source-${Date.now()}-${Math.random().toString(16).slice(2)}`,
  id: null,
  kind,
  label: '',
  tasks: [...TASK_OPTIONS],
  enabled: true,
  order: 0,
  source_value: kind === 'webcam' ? 0 : '',
  upload_id: null,
  upload: null,
  frame_processing_mode: 'frame_skip',
  process_every_n_frames: 1,
  target_frame_rate: 5,
  detector_model_key: null,
  tracker_model_key: null,
  anomaly_stage_1_model_key: null,
  anomaly_stage_2_model_key: null,
});

const hydrateSource = (source, fallbackIndex = 0) => ({
  clientKey: source.id ? `settings-source-${source.id}` : `settings-source-${fallbackIndex}-${Math.random().toString(16).slice(2)}`,
  id: source.id ?? null,
  kind: source.kind ?? 'camera_url',
  label: source.label ?? '',
  tasks: [...TASK_OPTIONS],
  enabled: source.enabled ?? true,
  order: source.order ?? fallbackIndex,
  source_value: source.source_value ?? (source.kind === 'webcam' ? 0 : ''),
  upload_id: source.upload_id ?? null,
  upload: source.upload ?? null,
  frame_processing_mode: source.frame_processing_mode ?? 'frame_skip',
  process_every_n_frames: Number.isFinite(source.process_every_n_frames) ? source.process_every_n_frames : 1,
  target_frame_rate: Number.isFinite(source.target_frame_rate) ? source.target_frame_rate : 5,
  detector_model_key: source.detector_model_key ?? null,
  tracker_model_key: source.tracker_model_key ?? null,
  anomaly_stage_1_model_key: source.anomaly_stage_1_model_key ?? null,
  anomaly_stage_2_model_key: source.anomaly_stage_2_model_key ?? null,
});

const createAlertRuleDraft = (ruleKind = 'detector') => ({
  clientKey: `settings-alert-rule-${Date.now()}-${Math.random().toString(16).slice(2)}`,
  id: null,
  source_id: null,
  source_ids: [],
  enabled: true,
  rule_label: '',
  rule_kind: ruleKind,
  signal_family: ruleKind === 'detector' ? 'detector' : 'anomaly_object',
  anomaly_target_kind: ruleKind === 'anomaly' ? 'object' : null,
  target_key: '',
  min_confidence: 0.5,
  anomaly_cutoff: 6,
  alert_level: 'medium',
  delivery_target_ids: [],
  isEditing: true,
});

const hydrateAlertRule = (rule, fallbackIndex = 0) => ({
  clientKey: rule.id ? `settings-alert-rule-${rule.id}` : `settings-alert-rule-${fallbackIndex}-${Math.random().toString(16).slice(2)}`,
  id: rule.id ?? null,
  source_id: rule.source_id ?? (Array.isArray(rule.source_ids) && rule.source_ids.length > 0 ? rule.source_ids[0] : null),
  source_ids: Array.isArray(rule.source_ids)
    ? rule.source_ids
    : (rule.source_id ? [rule.source_id] : []),
  enabled: rule.enabled ?? true,
  rule_label: rule.rule_label ?? '',
  rule_kind: rule.rule_kind ?? ((rule.signal_family || '').startsWith('anomaly_') ? 'anomaly' : 'detector'),
  signal_family: rule.signal_family ?? 'detector',
  anomaly_target_kind: rule.anomaly_target_kind
    ?? (rule.signal_family === 'anomaly_activity' ? 'behavior' : (rule.signal_family === 'anomaly_object' ? 'object' : null)),
  target_key: rule.target_key ?? '',
  min_confidence: Number.isFinite(rule.min_confidence) ? rule.min_confidence : 0.5,
  anomaly_cutoff: Number.isFinite(rule.anomaly_cutoff) ? rule.anomaly_cutoff : 6,
  alert_level: rule.alert_level ?? 'medium',
  delivery_target_ids: Array.isArray(rule.delivery_target_ids) ? rule.delivery_target_ids.map((item) => Number(item)) : [],
  isEditing: false,
});

const createAnomalyItemDraft = (item = '') => ({
  clientKey: `settings-anomaly-item-${Date.now()}-${Math.random().toString(16).slice(2)}`,
  item,
});

const hydrateAnomalyItem = (item, fallbackIndex = 0) => ({
  clientKey: `settings-anomaly-item-${fallbackIndex}-${Math.random().toString(16).slice(2)}`,
  item: typeof item === 'string' ? item : (item?.item ?? ''),
});

const createAnomalyBehaviorDraft = (value = '') => ({
  clientKey: `settings-anomaly-behavior-${Date.now()}-${Math.random().toString(16).slice(2)}`,
  value,
});

const hydrateAnomalyBehavior = (value, fallbackIndex = 0) => ({
  clientKey: `settings-anomaly-behavior-${fallbackIndex}-${Math.random().toString(16).slice(2)}`,
  value: value ?? '',
});

const createTelegramSubscriptionDraft = () => ({
  clientKey: `settings-telegram-subscription-${Date.now()}-${Math.random().toString(16).slice(2)}`,
  id: null,
  enabled: true,
  subscription_label: '',
  bot_token: '',
  chat_id: '',
  send_media: false,
  media_source: 'none',
});
const MASKED_SECRET_VALUE = '********';

const createStage2ProviderDraft = (providerKey) => {
  const option = STAGE2_PROVIDER_OPTIONS.find((item) => item.provider_key === providerKey);
  return {
    provider_key: providerKey,
    display_name: option?.label || providerKey,
    enabled: false,
    base_url: '',
    model_name: '',
    timeout_seconds: 30,
    auth_optional: Boolean(option?.authOptional),
    api_key: '',
    auth_token: '',
    secret_present: false,
    last_test_status: null,
    last_test_message: null,
    last_tested_at: null,
  };
};

const hydrateStage2ProviderSettings = (payload) => {
  const providerKey = payload?.provider_key || '';
  return {
    ...createStage2ProviderDraft(providerKey),
    ...payload,
    provider_key: providerKey,
    display_name: payload?.display_name ?? (STAGE2_PROVIDER_OPTIONS.find((item) => item.provider_key === providerKey)?.label || providerKey),
    enabled: Boolean(payload?.enabled),
    base_url: payload?.base_url ?? '',
    model_name: payload?.model_name ?? '',
    timeout_seconds: Number.isFinite(payload?.timeout_seconds) ? payload.timeout_seconds : 30,
    auth_optional: Boolean(payload?.auth_optional),
    api_key: payload?.api_key ?? '',
    auth_token: payload?.auth_token ?? '',
    secret_present: Boolean(payload?.secret_present),
    last_test_status: payload?.last_test_status ?? null,
    last_test_message: payload?.last_test_message ?? null,
    last_tested_at: payload?.last_tested_at ?? null,
  };
};

const getStage2ProviderOption = (providerKey) =>
  STAGE2_PROVIDER_OPTIONS.find((item) => item.provider_key === providerKey) || null;

const hydrateTelegramSubscription = (subscription, fallbackIndex = 0) => ({
  clientKey: subscription.id
    ? `settings-telegram-subscription-${subscription.id}`
    : `settings-telegram-subscription-${fallbackIndex}-${Math.random().toString(16).slice(2)}`,
  id: subscription.id ?? null,
  enabled: subscription.enabled ?? true,
  subscription_label: subscription.subscription_label ?? '',
  bot_token: subscription.bot_token ?? '',
  chat_id: subscription.chat_id ?? '',
  send_media: subscription.send_media ?? false,
  media_source: subscription.media_source ?? 'none',
});

const createAppleMessageSubscriptionDraft = () => ({
  clientKey: `settings-apple-message-subscription-${Date.now()}-${Math.random().toString(16).slice(2)}`,
  id: null,
  enabled: true,
  subscription_label: '',
  recipient_handle: '',
  service: 'iMessage',
});

const hydrateAppleMessageSubscription = (subscription, fallbackIndex = 0) => ({
  clientKey: subscription.id
    ? `settings-apple-message-subscription-${subscription.id}`
    : `settings-apple-message-subscription-${fallbackIndex}-${Math.random().toString(16).slice(2)}`,
  id: subscription.id ?? null,
  enabled: subscription.enabled ?? true,
  subscription_label: subscription.subscription_label ?? '',
  recipient_handle: subscription.recipient_handle ?? '',
  service: subscription.service ?? 'iMessage',
});

const createGoveeEndpointDraft = () => ({
  clientKey: `settings-govee-endpoint-${Date.now()}-${Math.random().toString(16).slice(2)}`,
  id: null,
  connector_key: 'govee',
  label: '',
  enabled: true,
  api_key: '',
  sku: '',
  device: '',
  device_name: '',
  capability_key: '',
  capability_type: '',
  capability_instance: '',
  capability_value: '',
  capability_value_label: '',
  input_kind: '',
});

const hydrateGoveeEndpoint = (endpoint, fallbackIndex = 0) => {
  const config = endpoint.config || {};
  return {
    clientKey: endpoint.id
      ? `settings-govee-endpoint-${endpoint.id}`
      : `settings-govee-endpoint-${fallbackIndex}-${Math.random().toString(16).slice(2)}`,
    id: endpoint.id ?? null,
    connector_key: endpoint.connector_key ?? 'govee',
    label: endpoint.label ?? '',
    enabled: endpoint.enabled ?? true,
    api_key: config.api_key ?? '',
    sku: config.sku ?? '',
    device: config.device ?? '',
    device_name: config.device_name ?? '',
    capability_key: config.capability_key ?? '',
    capability_type: config.capability_type ?? '',
    capability_instance: config.capability_instance ?? '',
    capability_value: config.capability_value ?? '',
    capability_value_label: config.capability_value_label ?? '',
    input_kind: config.input_kind ?? '',
    resolved: endpoint.resolved ?? true,
    unavailable_reason: endpoint.unavailable_reason ?? null,
  };
};

const sanitizeSourcesForApi = (sources) =>
  sources.map((source, index) => ({
    id: source.id ?? undefined,
    kind: source.kind,
    label: source.label.trim() || defaultSourceLabel(source, index, sources),
    tasks: [...TASK_OPTIONS],
    enabled: source.enabled,
    order: index,
    source_value: source.kind === 'video_upload' ? null : source.source_value,
    upload_id: source.kind === 'video_upload' ? source.upload_id : null,
    frame_processing_mode: source.kind === 'video_upload'
      ? 'frame_skip'
      : (source.frame_processing_mode || 'frame_skip'),
    process_every_n_frames: source.kind === 'video_upload'
      ? Math.max(1, Number(source.process_every_n_frames) || 1)
      : source.frame_processing_mode === 'target_frame_rate'
      ? 1
      : Math.max(1, Number(source.process_every_n_frames) || 1),
    target_frame_rate: source.kind === 'video_upload'
      ? null
      : source.frame_processing_mode === 'target_frame_rate'
      ? Math.max(0.1, Number(source.target_frame_rate) || 5)
      : null,
    detector_model_key: source.detector_model_key || null,
    tracker_model_key: source.tracker_model_key || null,
    reid_model_key: null,
    anomaly_stage_1_model_key: source.anomaly_stage_1_model_key || null,
    anomaly_stage_2_model_key: source.anomaly_stage_2_model_key || null,
  }));

const sanitizeAlertRulesForApi = (rules) =>
  rules.map((rule) => ({
    id: rule.id ?? undefined,
    source_ids: rule.source_ids,
    enabled: rule.enabled,
    rule_label: rule.rule_label?.trim() || null,
    rule_kind: rule.rule_kind,
    signal_family: rule.signal_family,
    anomaly_target_kind: rule.anomaly_target_kind,
    target_key: rule.target_key,
    min_confidence: Number(rule.min_confidence),
    anomaly_cutoff: rule.rule_kind === 'anomaly' ? Number(rule.anomaly_cutoff) : null,
    alert_level: rule.alert_level,
    delivery_target_ids: Array.isArray(rule.delivery_target_ids) ? rule.delivery_target_ids.map((item) => Number(item)) : [],
    trigger_key: 'alert_rule_trigger',
  }));

const sanitizeTelegramSubscriptionsForApi = (subscriptions) =>
  subscriptions.map((subscription) => ({
    id: subscription.id ?? undefined,
    enabled: subscription.enabled,
    subscription_label: subscription.subscription_label?.trim() || null,
    bot_token: subscription.bot_token.trim(),
    chat_id: subscription.chat_id.trim(),
    send_media: Boolean(subscription.send_media),
    media_source: subscription.media_source || 'none',
  }));

const sanitizeAppleMessageSubscriptionsForApi = (subscriptions) =>
  subscriptions.map((subscription) => ({
    id: subscription.id ?? undefined,
    enabled: subscription.enabled,
    subscription_label: subscription.subscription_label?.trim() || null,
    recipient_handle: subscription.recipient_handle.trim(),
    service: subscription.service,
  }));

const sanitizeGoveeEndpointsForApi = (endpoints) =>
  endpoints.map((endpoint) => ({
    id: endpoint.id ?? undefined,
    connector_key: 'govee',
    label: endpoint.label?.trim() || endpoint.device_name || 'Govee Light Connection',
    enabled: endpoint.enabled,
    config: {
      api_key: endpoint.api_key,
      sku: endpoint.sku,
      device: endpoint.device,
      device_name: endpoint.device_name,
      capability_key: endpoint.capability_key,
      capability_type: endpoint.capability_type,
      capability_instance: endpoint.capability_instance,
      capability_value: endpoint.capability_value,
      capability_value_label: endpoint.capability_value_label || null,
      input_kind: endpoint.input_kind || null,
    },
    delivery_capabilities: ['light_control'],
  }));

const buildAlertRuleSetupHint = (sources, errorDetail = null) => {
  if (!sources || sources.length === 0) {
    return 'Please connect and save a source first in the Sources tab.';
  }
  if (errorDetail) {
    return errorDetail;
  }
  return 'Alert rules will appear here after the source options finish loading.';
};

const stripFileExtension = (filename = '') => filename.replace(/\.[^/.]+$/, '');

const countMatchingSources = (sources, index, predicate) =>
  sources.slice(0, index + 1).filter(predicate).length;

const defaultSourceLabel = (source, index, sources) => {
  if (source.kind === 'webcam') {
    return `Webcam ${countMatchingSources(sources, index, (candidate) => candidate.kind === 'webcam')}`;
  }
  if (source.kind === 'video_upload' && source.upload?.original_filename) {
    return stripFileExtension(source.upload.original_filename) || source.upload.original_filename;
  }
  return `Camera ${countMatchingSources(
    sources,
    index,
    (candidate) =>
      candidate.kind !== 'webcam'
      && !(candidate.kind === 'video_upload' && candidate.upload?.original_filename),
  )}`;
};

const sourcePlaceholder = (kind) => {
  if (kind === 'webcam') {
    return 'Device index, e.g. 0';
  }
  return 'rtsp://, http://, or stream URL';
};

const describeFrameProcessingMode = (source) => {
  if (source.kind === 'video_upload') {
    return `Every ${Math.max(1, Number(source.process_every_n_frames) || 1)} frame(s)`;
  }
  if ((source.frame_processing_mode || 'frame_skip') === 'target_frame_rate') {
    return `Target ${Number(source.target_frame_rate) || 5} FPS`;
  }
  return `Every ${Math.max(1, Number(source.process_every_n_frames) || 1)} frame(s)`;
};

const createLaunchPlan = () => ({
  profile: 'cpu',
  template: 'active',
  sourcePreset: 'template default',
  cudaVisibleDevices: '0',
  openDashboard: true,
});

const buildLaunchCommand = (plan) => {
  const command = ['python3', 'run/run.py', 'start', '--template', plan.template, '--profile', plan.profile];
  if (plan.sourcePreset && plan.sourcePreset !== 'template default') {
    command.push('--source-preset', plan.sourcePreset);
  }
  if (plan.profile === 'cuda' && `${plan.cudaVisibleDevices}`.trim()) {
    command.push('--cuda-visible-devices', `${plan.cudaVisibleDevices}`.trim());
  }
  if (plan.openDashboard) {
    command.push('--open-dashboard');
  }
  return command.join(' ');
};

const groupThemeOptions = (themeOptions = []) =>
  themeOptions.reduce((result, option) => {
    const groupKey = option.group || 'core';
    if (!result[groupKey]) {
      result[groupKey] = [];
    }
    result[groupKey].push(option);
    return result;
  }, {});

const normalizeSourceKindLabel = (kind) => {
  if (!kind) {
    return null;
  }
  if (kind === 'camera_url') {
    return 'Camera URL';
  }
  if (kind === 'video_upload') {
    return 'Uploaded Video';
  }
  if (kind === 'webcam') {
    return 'Webcam';
  }
  return kind.replace(/_/g, ' ');
};
const formatLibraryModelId = (modelKey) => `${modelKey || ''}`.replace(/^builtin_/, '') || 'n/a';

const formatListLabel = (items = []) => items.filter(Boolean).join(', ');
const formatDetectorClassSummary = (items = []) => {
  const normalized = items.filter(Boolean);
  if (normalized.length <= 8) {
    return formatListLabel(normalized);
  }
  const visible = normalized.slice(0, 8);
  return `${formatListLabel(visible)}, and ${normalized.length - visible.length} more`;
};
const normalizeDetectorClassLabel = (value) => {
  const normalized = `${value || ''}`.trim();
  if (!normalized) {
    return null;
  }
  if (normalized.toLowerCase() === 'person') {
    return 'person';
  }
  if (normalized.toLowerCase() === 'bag') {
    return 'bag';
  }
  return normalized.replace(/_/g, ' ');
};
const getModelClasses = (option) => {
  const capabilities = option.capabilities || {};
  const rawClasses = capabilities.classes || capabilities.detector_classes || [];
  if (!Array.isArray(rawClasses)) {
    return [];
  }
  return rawClasses.map(normalizeDetectorClassLabel).filter(Boolean);
};
const getRuntimeTargets = (option) => {
  const capabilities = option.capabilities || {};
  const runtimeTargets = capabilities.runtime_targets || option.runtime?.runtime_targets || [];
  if (!Array.isArray(runtimeTargets)) {
    return [];
  }
  return runtimeTargets.map((value) => `${value || ''}`.trim().toUpperCase()).filter(Boolean);
};
const hasExpandedDetectorClasses = (classes) =>
  classes.some((item) => !['person', 'bag'].includes(`${item}`.toLowerCase()));

const describeModelOption = (option) => {
  const name = option.display_name || option.model_key;
  const runtime = option.runtime || {};
  const adapter = option.adapter || '';
  switch (option.stage) {
    case 'detector':
      return `${name} is used to find people and bags in each frame before tracking starts.`;
    case 'tracker':
      return `${name} is used to keep the same person or bag connected across frames after detection.`;
    case 'anomaly_stage_1':
      return `${name} is used as the first anomaly pass to watch for presence and timing changes worth reviewing.`;
    case 'anomaly_stage_2':
      if (adapter === 'prompt_rules_stage_2') {
        return `${name} uses the saved anomaly prompts and object or activity lists to label suspicious events.`;
      }
      if (adapter === 'passthrough_stage_2') {
        return `${name} keeps Stage 1 anomaly events moving without adding prompt-based interpretation.`;
      }
      return `${name} is used as the second anomaly pass to interpret or enrich anomaly events.`;
    default:
      return `${name} is available in the current model library.`;
  }
};

const describeModelFit = (option) => {
  const runtime = option.runtime || {};
  if (option.stage === 'detector') {
    return option.requires_gpu
      ? 'Best when you want the standard detector on a GPU-backed pipeline.'
      : 'Best when you want the standard detector on a CPU-safe pipeline.';
  }
  if (option.stage === 'tracker') {
    return 'Best when you want stable movement tracking after detection.';
  }
  if (option.stage === 'anomaly_stage_1') {
    return 'Best when you want a low-cost first-pass anomaly screen.';
  }
  if (option.stage === 'anomaly_stage_2' && runtime.prompt_yaml_path) {
    return 'Best when you want alerting and anomaly interpretation tied to the saved prompts.';
  }
  if (option.stage === 'anomaly_stage_2' && option.adapter === 'passthrough_stage_2') {
    return 'Best when you want to keep the anomaly lane simple and skip prompt interpretation.';
  }
  return 'Available for specialized or compatibility use.';
};

const SettingsPage = ({
  forcedTab = null,
  hideTabBar = false,
  pageTitle = 'Settings',
  pageSubtitle = 'Configure monitor run, sources, models, and repository initialization from one workspace.',
  themeOptions = [],
  currentThemeKey = 'fidelity-light',
  appearanceLoaded = false,
  appearanceError = '',
  isSavingAppearance = false,
  onSaveAppearance = null,
}) => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [sources, setSources] = useState(() => {
    const saved = localStorage.getItem('settingsSourcesDraft');
    if (!saved) {
      return [createSourceDraft()];
    }
    try {
      return JSON.parse(saved);
    } catch (error) {
      return [createSourceDraft()];
    }
  });
  const [isSaving, setIsSaving] = useState(false);
  const [isSavingBindings, setIsSavingBindings] = useState(false);
  const [isSavingMountedModels, setIsSavingMountedModels] = useState(false);
  const [isSavingAnomalyPrompts, setIsSavingAnomalyPrompts] = useState(false);
  const [isSavingAlertRules, setIsSavingAlertRules] = useState(false);
  const [isSavingTelegramSubscriptions, setIsSavingTelegramSubscriptions] = useState(false);
  const [isSavingAppleMessageSubscriptions, setIsSavingAppleMessageSubscriptions] = useState(false);
  const [isSavingGoveeEndpoints, setIsSavingGoveeEndpoints] = useState(false);
  const [isSavingStage2ProviderSettings, setIsSavingStage2ProviderSettings] = useState(false);
  const [isSavingConnectorZooRepoSettings, setIsSavingConnectorZooRepoSettings] = useState(false);
  const [banner, setBanner] = useState(null);
  const [mountedModels, setMountedModels] = useState({});
  const [rowErrors, setRowErrors] = useState({});
  const [alertRuleErrors, setAlertRuleErrors] = useState({});
  const [telegramSubscriptionErrors, setTelegramSubscriptionErrors] = useState({});
  const [appleMessageSubscriptionErrors, setAppleMessageSubscriptionErrors] = useState({});
  const [goveeEndpointErrors, setGoveeEndpointErrors] = useState({});
  const [stage2ProviderErrors, setStage2ProviderErrors] = useState({});
  const [busyUploads, setBusyUploads] = useState({});
  const [uploadFeedback, setUploadFeedback] = useState({});
  const [busyTelegramTests, setBusyTelegramTests] = useState({});
  const [busyAppleMessageTests, setBusyAppleMessageTests] = useState({});
  const [busyGoveeTests, setBusyGoveeTests] = useState({});
  const [busyGoveeDiscovery, setBusyGoveeDiscovery] = useState({});
  const [busyStage2ProviderTests, setBusyStage2ProviderTests] = useState({});
  const [modelOptionCatalog, setModelOptionCatalog] = useState({ model_zoo: null, stages: [] });
  const [defaultBindings, setDefaultBindings] = useState({});
  const modelRegistryLoadRef = useRef(null);
  const [alertRules, setAlertRules] = useState([]);
  const [persistedAlertRules, setPersistedAlertRules] = useState([]);
  const [telegramSubscriptions, setTelegramSubscriptions] = useState([]);
  const [appleMessageSubscriptions, setAppleMessageSubscriptions] = useState([]);
  const [goveeEndpoints, setGoveeEndpoints] = useState([]);
  const [genericConnectorEndpoints, setGenericConnectorEndpoints] = useState([]);
  const [stage2ProviderSettings, setStage2ProviderSettings] = useState(
    STAGE2_PROVIDER_OPTIONS.map((option) => createStage2ProviderDraft(option.provider_key))
  );
  const [alertRuleOptions, setAlertRuleOptions] = useState({ sources: [] });
  const [alertRuleLoadHint, setAlertRuleLoadHint] = useState('');
  const [connectorSubTab, setConnectorSubTab] = useState('connections');
  const [connectorZooRepoSettings, setConnectorZooRepoSettings] = useState({ catalog_url: '' });
  const [repoConnectorZooCatalog, setRepoConnectorZooCatalog] = useState(normalizeRepoConnectorZooPayload({}));
  const [installingRepoConnectorKey, setInstallingRepoConnectorKey] = useState('');
  const [anomalyItems, setAnomalyItems] = useState([]);
  const [anomalyBehaviors, setAnomalyBehaviors] = useState([]);
  const [standardPromptSettings, setStandardPromptSettings] = useState(EMPTY_PROMPT_SETTINGS);
  const [modelLibrarySubTab, setModelLibrarySubTab] = useState('inventory');
  const [expandedInventoryStages, setExpandedInventoryStages] = useState({});
  const [launchPlan, setLaunchPlan] = useState(() => {
    const saved = localStorage.getItem('settingsLaunchPlanDraft');
    if (!saved) {
      return createLaunchPlan();
    }
    try {
      return {
        ...createLaunchPlan(),
        ...JSON.parse(saved),
      };
    } catch (error) {
      return createLaunchPlan();
    }
  });
  const [draftThemeKey, setDraftThemeKey] = useState(currentThemeKey);
  const [appearanceMessage, setAppearanceMessage] = useState(null);
  const [goveeDiscoveryResults, setGoveeDiscoveryResults] = useState({});
  const [goveeDiscoveryMessages, setGoveeDiscoveryMessages] = useState({});
  const [mountedModelConflict, setMountedModelConflict] = useState(null);
  const rawRequestedTab = forcedTab || searchParams.get('tab');
  const requestedTab = rawRequestedTab === 'run' ? 'monitoring' : rawRequestedTab;
  const allowedTabs = forcedTab ? [...SETTINGS_TABS, ...STANDALONE_PAGE_TABS] : SETTINGS_TABS;
  const activeTab = allowedTabs.some((tab) => tab.key === requestedTab)
    ? requestedTab
    : (forcedTab || 'sources');

  useEffect(() => {
    if (forcedTab) {
      return;
    }
    if (rawRequestedTab === 'run') {
      setSearchParams({ tab: 'monitoring' }, { replace: true });
      return;
    }
    if (!requestedTab || !SETTINGS_TABS.some((tab) => tab.key === requestedTab)) {
      setSearchParams({ tab: 'monitoring' }, { replace: true });
    }
  }, [forcedTab, rawRequestedTab, requestedTab, setSearchParams]);

  useEffect(() => {
    localStorage.setItem('settingsSourcesDraft', JSON.stringify(sources));
  }, [sources]);

  useEffect(() => {
    localStorage.setItem('settingsLaunchPlanDraft', JSON.stringify(launchPlan));
  }, [launchPlan]);

  useEffect(() => {
    setDraftThemeKey(getThemeOption(currentThemeKey).key);
  }, [currentThemeKey]);

  const reloadAlertRuleState = async ({ includeRules = true, sourcesSnapshot = [] } = {}) => {
    try {
      const optionResponse = await fetchWithTimeout(`${BaseURL}/settings/alert-rule-options`, {}, 30000);
      const optionData = await parseApiJson(optionResponse, 'Failed to load alert rule options');
      if (!includeRules) {
        setAlertRuleOptions(optionData || { sources: [] });
        setAlertRuleLoadHint(buildAlertRuleSetupHint(sourcesSnapshot));
        return;
      }
      const ruleResponse = await fetchWithTimeout(`${BaseURL}/settings/trigger-rules`, {}, 30000);
      let ruleData = [];
      try {
        ruleData = await parseApiJson(ruleResponse, 'Failed to load trigger rules');
        if (!Array.isArray(ruleData)) {
          throw new Error('Trigger rules response was not a list');
        }
      } catch (error) {
        const legacyResponse = await fetchWithTimeout(`${BaseURL}/settings/alert-rules`, {}, 30000);
        ruleData = await parseApiJson(legacyResponse, 'Failed to load alert rules');
      }
      const hydratedRules = (Array.isArray(ruleData) ? ruleData : []).map((rule, index) => hydrateAlertRule(rule, index));
      setAlertRules(hydratedRules);
      setPersistedAlertRules(hydratedRules);
      setAlertRuleOptions(optionData || { sources: [] });
      setAlertRuleLoadHint(buildAlertRuleSetupHint(sourcesSnapshot));
    } catch (error) {
      setAlertRules([]);
      setPersistedAlertRules([]);
      setAlertRuleOptions({ sources: [] });
      setAlertRuleLoadHint(buildAlertRuleSetupHint(sourcesSnapshot, error.message));
    }
  };

  const reloadTelegramSubscriptionState = async () => {
    const data = await fetchJson(
      `${BaseURL}/settings/telegram-trigger-subscriptions`,
      {},
      'Failed to load Telegram trigger subscriptions',
      30000,
    );
    setTelegramSubscriptions(normalizeListPayload(data).map((subscription, index) => hydrateTelegramSubscription(subscription, index)));
  };

  const reloadAppleMessageSubscriptionState = async () => {
    const data = await fetchJson(
      `${BaseURL}/settings/apple-message-trigger-subscriptions`,
      {},
      'Failed to load Apple Messages trigger subscriptions',
      30000,
    );
    setAppleMessageSubscriptions(normalizeListPayload(data).map((subscription, index) => hydrateAppleMessageSubscription(subscription, index)));
  };

  const reloadGoveeEndpointState = async () => {
    const data = await fetchJson(
      `${BaseURL}/settings/govee-connector-endpoints`,
      {},
      'Failed to load Govee connector endpoints',
      30000,
    );
    setGoveeEndpoints(normalizeListPayload(data).map((endpoint, index) => hydrateGoveeEndpoint(endpoint, index)));
  };

  const reloadGenericConnectorEndpointState = async () => {
    const data = await fetchJson(
      `${BaseURL}/settings/connector-endpoints`,
      {},
      'Failed to load connector endpoints',
      30000,
    );
    setGenericConnectorEndpoints(
      normalizeListPayload(data).filter(
        (endpoint) => !['telegram', 'apple_messages', 'govee'].includes(endpoint.connector_key),
      ),
    );
  };

  const reloadStage2ProviderSettings = async () => {
    const response = await fetch(`${BaseURL}/settings/stage2-provider-settings`);
    if (!response.ok) {
      let detail = null;
      try {
        const payload = await response.json();
        detail = payload?.detail || null;
      } catch (error) {
        detail = null;
      }
      throw new Error(detail || 'Failed to load Stage 2 provider settings');
    }
    const data = await response.json();
    const nextByKey = new Map(
      normalizeListPayload(data).map((item) => [item.provider_key, hydrateStage2ProviderSettings(item)]),
    );
    setStage2ProviderSettings(
      STAGE2_PROVIDER_OPTIONS.map((option) =>
        nextByKey.get(option.provider_key) || createStage2ProviderDraft(option.provider_key)
      ),
    );
  };

  const reloadConnectorZooRepoSettings = async () => {
    const data = await fetchJson(
      `${BaseURL}/settings/connector-zoo-repo`,
      {},
      'Failed to load Connector Zoo repo settings',
      30000,
    );
    setConnectorZooRepoSettings({
      catalog_url: data?.catalog_url ?? '',
    });
  };

  const reloadRepoConnectorZooCatalog = async () => {
    const data = await fetchJson(
      `${BaseURL}/connector-zoo/repo`,
      {},
      'Failed to refresh Connector Zoo',
      30000,
    );
    setRepoConnectorZooCatalog(normalizeRepoConnectorZooPayload(data));
  };

  useEffect(() => {
    const bootstrapSettings = async () => {
      const loadInputSources = async () => {
        const sourceResponse = await fetchWithTimeout(`${BaseURL}/settings/input-sources`, {}, 30000);
        const parsed = await parseApiJson(sourceResponse, 'Failed to load input source settings');
        return Array.isArray(parsed) ? parsed : [];
      };

      const [modelOutcome, sourceOutcome] = await Promise.allSettled([
        reloadModelRegistryState(),
        loadInputSources(),
      ]);

      if (modelOutcome.status === 'fulfilled') {
        setBanner((current) => (
          current?.kind === 'error' && String(current.text || '').includes('Model registry')
            ? null
            : current
        ));
      } else {
        console.warn('Model registry settings failed to load', modelOutcome.reason);
        setBanner({
          kind: 'error',
          text: formatApiError(
            modelOutcome.reason,
            'Model registry settings failed to load. Refresh the page or restart the webapp container.',
          ),
        });
      }

      let sourceData = [];
      if (sourceOutcome.status === 'fulfilled') {
        sourceData = sourceOutcome.value;
      } else {
        console.warn('Input sources API unavailable; using local draft', sourceOutcome.reason);
        setBanner((current) => current ?? {
          kind: 'error',
          text: formatApiError(
            sourceOutcome.reason,
            'Saved sources could not be loaded from the server. Showing your local draft.',
          ),
        });
      }
      const hydratedSources = sourceData.length > 0
        ? sourceData.map((source, index) => hydrateSource(source, index))
        : [createSourceDraft()];
      setSources(hydratedSources);

      try {
        let standardPromptData = EMPTY_PROMPT_SETTINGS;
        const standardPromptResponse = await fetchWithTimeout(`${BaseURL}/settings/anomaly-prompts/standard`, {}, 30000);
        if (standardPromptResponse.ok) {
          standardPromptData = await parseApiJson(standardPromptResponse, 'Failed to load standard anomaly prompts');
          setStandardPromptSettings({
            anomaly_items: standardPromptData.anomaly_items || [],
            anomaly_behaviors: standardPromptData.anomaly_behaviors || [],
          });
        }
        const promptResponse = await fetchWithTimeout(`${BaseURL}/settings/anomaly-prompts`, {}, 30000);
        if (promptResponse.ok) {
          const promptData = await parseApiJson(promptResponse, 'Failed to load anomaly prompts');
          setAnomalyItems((promptData.anomaly_items || []).map((item, index) => hydrateAnomalyItem(item, index)));
          setAnomalyBehaviors((promptData.anomaly_behaviors || []).map((item, index) => hydrateAnomalyBehavior(item, index)));
        } else {
          setAnomalyItems((standardPromptData.anomaly_items || []).map((item, index) => hydrateAnomalyItem(item, index)));
          setAnomalyBehaviors((standardPromptData.anomaly_behaviors || []).map((item, index) => hydrateAnomalyBehavior(item, index)));
        }
      } catch (error) {
        console.warn('Anomaly prompt settings failed to load', error);
      }

      const optionalConnectorReloads = [
        reloadTelegramSubscriptionState,
        reloadAppleMessageSubscriptionState,
        reloadGoveeEndpointState,
        reloadGenericConnectorEndpointState,
        reloadStage2ProviderSettings,
        reloadConnectorZooRepoSettings,
      ];
      for (const reload of optionalConnectorReloads) {
        try {
          await reload();
        } catch (error) {
          console.warn('Optional connector settings failed to load', error);
        }
      }

      await reloadAlertRuleState({
        sourcesSnapshot: sourceData,
      });
    };

    bootstrapSettings();
  }, []);

  useEffect(() => {
    if (activeTab !== 'connectors' || connectorSubTab !== 'connector-zoo') {
      return;
    }
    reloadRepoConnectorZooCatalog().catch((error) => {
      setBanner({
        kind: 'error',
        text: formatApiError(error, 'Failed to refresh Connector Zoo.'),
      });
    });
  }, [activeTab, connectorSubTab]);

  const setSourceField = (clientKey, field, value) => {
    setSources((previous) =>
      previous.map((source, index) =>
        source.clientKey === clientKey
          ? {
              ...source,
              [field]: value,
              order: index,
            }
          : source
      )
    );
  };

  const alertRuleOptionSources = alertRuleOptions.sources || [];
  const groupedThemeOptions = groupThemeOptions(themeOptions);
  const themeGroupsInOrder = ['light', 'dark', 'accessible', 'core']
    .filter((groupKey) => Array.isArray(groupedThemeOptions[groupKey]) && groupedThemeOptions[groupKey].length > 0);
  const alertRuleOptionsBySource = alertRuleOptionSources.reduce((result, sourceOption) => {
    result[sourceOption.source_id] = sourceOption;
    return result;
  }, {});

  const getSignalOptionsForSource = (sourceId, signalFamily) =>
    (alertRuleOptionsBySource[sourceId]?.signal_options || []).find((entry) => entry.signal_family === signalFamily);

  const getPreferredSignalFamily = (sourceId) => {
    const signalOptions = alertRuleOptionsBySource[sourceId]?.signal_options || [];
    const preferred = signalOptions.find((entry) => (entry.options || []).length > 0 && !entry.unavailable_reason);
    return preferred?.signal_family || 'detector';
  };

  const getFirstAvailableTargetKey = (sourceId, signalFamily) => {
    const signalOptions = getSignalOptionsForSource(sourceId, signalFamily);
    const options = signalOptions?.options || [];
    return options.length > 0 ? options[0].key : '';
  };

  const getResolvedTargetKey = (sourceId, signalFamily, currentTargetKey) => {
    const signalOptions = getSignalOptionsForSource(sourceId, signalFamily);
    const options = signalOptions?.options || [];
    if (options.some((option) => option.key === currentTargetKey)) {
      return currentTargetKey;
    }
    return options.length > 0 ? options[0].key : '';
  };

  const addAlertRule = (ruleKind = 'detector') => {
    setAlertRules((previous) => [
      ...previous,
      createAlertRuleDraft(ruleKind),
    ]);
  };

  const removeAlertRule = (clientKey) => {
    setAlertRules((previous) => previous.filter((rule) => rule.clientKey !== clientKey));
    setAlertRuleErrors((previous) => {
      const next = { ...previous };
      delete next[clientKey];
      return next;
    });
  };

  const editAlertRule = (clientKey) => {
    setAlertRules((previous) =>
      previous.map((rule) =>
        rule.clientKey === clientKey
          ? { ...rule, isEditing: true }
          : rule
      )
    );
  };

  const cancelAlertRuleEdit = (clientKey) => {
    setAlertRules((previous) => {
      const currentRule = previous.find((rule) => rule.clientKey === clientKey);
      if (!currentRule) {
        return previous;
      }
      if (!currentRule.id) {
        return previous.filter((rule) => rule.clientKey !== clientKey);
      }
      const persistedRule = persistedAlertRules.find((rule) => rule.id === currentRule.id);
      if (!persistedRule) {
        return previous.filter((rule) => rule.clientKey !== clientKey);
      }
      return previous.map((rule) => (rule.clientKey === clientKey ? { ...persistedRule } : rule));
    });
    setAlertRuleErrors((previous) => {
      const next = { ...previous };
      delete next[clientKey];
      return next;
    });
  };

  const setAlertRuleField = (clientKey, field, value) => {
    setAlertRules((previous) =>
      previous.map((rule) =>
        rule.clientKey === clientKey
          ? {
              ...rule,
              [field]: value,
            }
          : rule
      )
    );
  };

  const toggleAlertRuleSource = (clientKey, sourceId, checked) => {
    setAlertRules((previous) =>
      previous.map((rule) => {
        if (rule.clientKey !== clientKey) {
          return rule;
        }
        const nextSourceIds = new Set(rule.source_ids || []);
        if (checked) {
          nextSourceIds.add(sourceId);
        } else {
          nextSourceIds.delete(sourceId);
        }
        const orderedIds = sources
          .filter((source) => nextSourceIds.has(source.id))
          .map((source) => source.id);
        const nextSourceId = orderedIds[0] ?? null;
        const nextTargetKey = nextSourceId
          ? getResolvedTargetKey(nextSourceId, rule.signal_family, rule.target_key)
          : '';
        return {
          ...rule,
          source_ids: orderedIds,
          source_id: nextSourceId,
          target_key: nextTargetKey,
        };
      })
    );
  };

  const setAlertRuleSignalFamily = (clientKey, signalFamily) => {
    setAlertRules((previous) =>
      previous.map((rule) =>
        rule.clientKey === clientKey
          ? {
              ...rule,
              signal_family: signalFamily,
              anomaly_target_kind: signalFamily === 'anomaly_activity' ? 'behavior' : (signalFamily === 'anomaly_object' ? 'object' : null),
              target_key: rule.source_ids?.[0] ? getFirstAvailableTargetKey(rule.source_ids[0], signalFamily) : '',
            }
          : rule
      )
    );
  };

  const toggleAlertRuleConnectorTarget = (clientKey, connectorId, checked) => {
    setAlertRules((previous) =>
      previous.map((rule) => {
        if (rule.clientKey !== clientKey) {
          return rule;
        }
        const nextIds = new Set((rule.delivery_target_ids || []).map((item) => Number(item)));
        if (checked) {
          nextIds.add(Number(connectorId));
        } else {
          nextIds.delete(Number(connectorId));
        }
        return {
          ...rule,
          delivery_target_ids: Array.from(nextIds).sort((left, right) => left - right),
        };
      })
    );
  };

  const saveAppearanceSettings = async () => {
    if (!onSaveAppearance) {
      return;
    }
    setAppearanceMessage(null);
    try {
      const savedThemeKey = await onSaveAppearance(draftThemeKey);
      setDraftThemeKey(getThemeOption(savedThemeKey).key);
      setAppearanceMessage({ kind: 'success', text: `Theme updated to ${getThemeOption(savedThemeKey).label}.` });
    } catch (error) {
      setAppearanceMessage(null);
    }
  };

  const setAlertRuleKind = (clientKey, ruleKind) => {
    setAlertRules((previous) =>
      previous.map((rule) =>
        rule.clientKey === clientKey
          ? {
              ...rule,
              rule_kind: ruleKind,
              signal_family: ruleKind === 'detector' ? 'detector' : 'anomaly_object',
              anomaly_target_kind: ruleKind === 'anomaly' ? 'object' : null,
              target_key: rule.source_ids?.[0]
                ? getFirstAvailableTargetKey(rule.source_ids[0], ruleKind === 'detector' ? 'detector' : 'anomaly_object')
                : '',
              anomaly_cutoff: ruleKind === 'anomaly' ? (rule.anomaly_cutoff || 6) : null,
            }
          : rule
      )
    );
  };

  useEffect(() => {
    setAlertRules((previous) => {
      let changed = false;
      const nextRules = previous.map((rule) => {
        const selectedSourceId = rule.source_ids?.[0];
        if (!selectedSourceId || !rule.isEditing) {
          return rule;
        }
        const resolvedTargetKey = getResolvedTargetKey(selectedSourceId, rule.signal_family, rule.target_key);
        if (resolvedTargetKey === rule.target_key) {
          return rule;
        }
        changed = true;
        return {
          ...rule,
          target_key: resolvedTargetKey,
        };
      });
      return changed ? nextRules : previous;
    });
  }, [alertRuleOptionSources]);

  const addTelegramSubscription = () => {
    setTelegramSubscriptions((previous) => [
      ...previous,
      createTelegramSubscriptionDraft(),
    ]);
  };

  const removeTelegramSubscription = (clientKey) => {
    setTelegramSubscriptions((previous) =>
      previous.filter((subscription) => subscription.clientKey !== clientKey)
    );
    setTelegramSubscriptionErrors((previous) => {
      const next = { ...previous };
      delete next[clientKey];
      return next;
    });
  };

  const setTelegramSubscriptionField = (clientKey, field, value) => {
    setTelegramSubscriptions((previous) =>
      previous.map((subscription) =>
        subscription.clientKey === clientKey
          ? {
              ...subscription,
              [field]: value,
            }
          : subscription
      )
    );
  };

  const addAppleMessageSubscription = () => {
    setAppleMessageSubscriptions((previous) => [
      ...previous,
      createAppleMessageSubscriptionDraft(),
    ]);
  };

  const removeAppleMessageSubscription = (clientKey) => {
    setAppleMessageSubscriptions((previous) =>
      previous.filter((subscription) => subscription.clientKey !== clientKey)
    );
    setAppleMessageSubscriptionErrors((previous) => {
      const next = { ...previous };
      delete next[clientKey];
      return next;
    });
  };

  const setAppleMessageSubscriptionField = (clientKey, field, value) => {
    setAppleMessageSubscriptions((previous) =>
      previous.map((subscription) =>
        subscription.clientKey === clientKey
          ? {
              ...subscription,
              [field]: value,
            }
          : subscription
      )
    );
  };

  const addGoveeEndpoint = () => {
    setGoveeEndpoints((previous) => [...previous, createGoveeEndpointDraft()]);
  };

  const removeGoveeEndpoint = (clientKey) => {
    setGoveeEndpoints((previous) => previous.filter((endpoint) => endpoint.clientKey !== clientKey));
    setGoveeEndpointErrors((previous) => {
      const next = { ...previous };
      delete next[clientKey];
      return next;
    });
    setGoveeDiscoveryResults((previous) => {
      const next = { ...previous };
      delete next[clientKey];
      return next;
    });
    setGoveeDiscoveryMessages((previous) => {
      const next = { ...previous };
      delete next[clientKey];
      return next;
    });
  };

  const setGoveeEndpointField = (clientKey, field, value) => {
    setGoveeEndpoints((previous) =>
      previous.map((endpoint) =>
        endpoint.clientKey === clientKey
          ? {
              ...endpoint,
              [field]: value,
            }
          : endpoint
      )
    );
  };

  const applyGoveeDeviceSelection = (clientKey, deviceKey) => {
    const devices = goveeDiscoveryResults[clientKey] || [];
    const selectedDevice = devices.find((device) => `${device.sku}:${device.device}` === deviceKey);
    setGoveeEndpoints((previous) =>
      previous.map((endpoint) => {
        if (endpoint.clientKey !== clientKey) {
          return endpoint;
        }
        if (!selectedDevice) {
          return {
            ...endpoint,
            sku: '',
            device: '',
            device_name: '',
            capability_key: '',
            capability_type: '',
            capability_instance: '',
            capability_value: '',
            capability_value_label: '',
            input_kind: '',
          };
        }
        const firstCapability = (selectedDevice.capability_options || [])[0];
        return {
          ...endpoint,
          sku: selectedDevice.sku,
          device: selectedDevice.device,
          device_name: selectedDevice.device_name,
          capability_key: firstCapability?.key || '',
          capability_type: firstCapability?.capability_type || '',
          capability_instance: firstCapability?.instance || '',
          capability_value: firstCapability?.default_value ?? '',
          capability_value_label: '',
          input_kind: firstCapability?.input_kind || '',
        };
      })
    );
  };

  const applyGoveeCapabilitySelection = (clientKey, capabilityKey) => {
    const endpoint = goveeEndpoints.find((item) => item.clientKey === clientKey);
    const deviceEntry = (goveeDiscoveryResults[clientKey] || []).find(
      (device) => device.sku === endpoint?.sku && device.device === endpoint?.device,
    );
    const capability = (deviceEntry?.capability_options || []).find((item) => item.key === capabilityKey);
    setGoveeEndpoints((previous) =>
      previous.map((item) =>
        item.clientKey === clientKey
          ? {
              ...item,
              capability_key: capability?.key || '',
              capability_type: capability?.capability_type || '',
              capability_instance: capability?.instance || '',
              capability_value: capability?.default_value ?? '',
              capability_value_label: '',
              input_kind: capability?.input_kind || '',
            }
          : item
      )
    );
  };

  const addSource = (kind = 'camera_url') => {
    setSources((previous) => [...previous, createSourceDraft(kind)]);
  };

  const removeSource = (clientKey) => {
    setUploadFeedback((previous) => {
      const next = { ...previous };
      delete next[clientKey];
      return next;
    });
    setSources((previous) => {
      const next = previous.filter((source) => source.clientKey !== clientKey);
      return next.length > 0 ? next : [createSourceDraft()];
    });
  };

  const validateSources = () => {
    const nextErrors = {};
    sources.forEach((source) => {
      if (source.kind === 'video_upload' && !source.upload_id) {
        nextErrors[source.clientKey] = 'Upload a video file before saving.';
      } else if (source.kind !== 'video_upload' && `${source.source_value ?? ''}`.trim() === '') {
        nextErrors[source.clientKey] = 'Source value is required.';
      } else if ((source.frame_processing_mode || 'frame_skip') === 'target_frame_rate') {
        if (Number.isNaN(Number(source.target_frame_rate)) || Number(source.target_frame_rate) <= 0) {
          nextErrors[source.clientKey] = 'Target frame rate must be greater than 0.';
        }
      } else if (Number.isNaN(Number(source.process_every_n_frames)) || Number(source.process_every_n_frames) < 1) {
        nextErrors[source.clientKey] = 'Frame skip must be 1 or greater.';
      }
    });
    setRowErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const validateAlertRules = () => {
    const nextErrors = {};
    alertRules.forEach((rule) => {
      if (!Array.isArray(rule.source_ids) || rule.source_ids.length === 0) {
        nextErrors[rule.clientKey] = 'Select at least one camera.';
        return;
      }
      if (!rule.target_key) {
        nextErrors[rule.clientKey] = 'Select a target for the rule.';
        return;
      }
      for (const sourceId of rule.source_ids) {
        const sourceSignalOptions = getSignalOptionsForSource(sourceId, rule.signal_family);
        const validTargets = new Set((sourceSignalOptions?.options || []).map((option) => option.key.toLowerCase()));
        if (sourceSignalOptions?.unavailable_reason) {
          nextErrors[rule.clientKey] = sourceSignalOptions.unavailable_reason;
          return;
        }
        if (!validTargets.has(rule.target_key.toLowerCase())) {
          nextErrors[rule.clientKey] = 'Select a valid target from the prepared options.';
          return;
        }
      }
      if (rule.rule_kind === 'detector') {
        if (Number.isNaN(Number(rule.min_confidence)) || Number(rule.min_confidence) < 0 || Number(rule.min_confidence) > 1) {
          nextErrors[rule.clientKey] = 'Confidence must be between 0.0 and 1.0.';
        }
      } else if (Number.isNaN(Number(rule.anomaly_cutoff)) || Number(rule.anomaly_cutoff) < 1 || Number(rule.anomaly_cutoff) > 10) {
        nextErrors[rule.clientKey] = 'Anomaly trigger cutoff must be between 1 and 10.';
      }
    });
    setAlertRuleErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const validateTelegramSubscriptions = () => {
    const nextErrors = {};
    telegramSubscriptions.forEach((subscription) => {
      if (!subscription.bot_token.trim()) {
        nextErrors[subscription.clientKey] = 'Bot token is required.';
      } else if (subscription.bot_token.trim() === MASKED_SECRET_VALUE) {
        nextErrors[subscription.clientKey] = 'Paste the new bot token value before saving.';
      } else if (!subscription.chat_id.trim()) {
        nextErrors[subscription.clientKey] = 'Chat ID is required.';
      }
    });
    setTelegramSubscriptionErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const validateAppleMessageSubscriptions = () => {
    const nextErrors = {};
    appleMessageSubscriptions.forEach((subscription) => {
      if (!subscription.recipient_handle.trim()) {
        nextErrors[subscription.clientKey] = 'Recipient handle is required.';
      } else if (!['iMessage', 'SMS'].includes(subscription.service)) {
        nextErrors[subscription.clientKey] = 'Service must be iMessage or SMS.';
      }
    });
    setAppleMessageSubscriptionErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const validateGoveeEndpoints = () => {
    const nextErrors = {};
    goveeEndpoints.forEach((endpoint) => {
      if (!endpoint.api_key.trim()) {
        nextErrors[endpoint.clientKey] = 'API key is required.';
      } else if (!endpoint.sku || !endpoint.device) {
        nextErrors[endpoint.clientKey] = 'Discover and select a Govee light device first.';
      } else if (!endpoint.capability_type || !endpoint.capability_instance) {
        nextErrors[endpoint.clientKey] = 'Select a supported Govee light action.';
      } else if (endpoint.capability_value === '' || endpoint.capability_value === null || endpoint.capability_value === undefined) {
        nextErrors[endpoint.clientKey] = 'Select or enter the action value to send on trigger.';
      }
    });
    setGoveeEndpointErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const validateStage2ProviderSettings = () => {
    const nextErrors = {};
    stage2ProviderSettings.forEach((provider) => {
      if (!provider.enabled) {
        return;
      }
      const option = getStage2ProviderOption(provider.provider_key);
      const secretField = option?.secretField || 'api_key';
      const secretValue = String(provider[secretField] || '').trim();
      if (!provider.base_url.trim()) {
        nextErrors[provider.provider_key] = 'Base URL is required when the provider is enabled.';
      } else if (!/^https?:\/\//i.test(provider.base_url.trim())) {
        nextErrors[provider.provider_key] = 'Base URL must start with http:// or https://.';
      } else if (!provider.model_name.trim()) {
        nextErrors[provider.provider_key] = 'Model name is required when the provider is enabled.';
      } else if (!provider.auth_optional && !secretValue) {
        nextErrors[provider.provider_key] = `${option?.secretLabel || 'Credential'} is required when the provider is enabled.`;
      }
    });
    setStage2ProviderErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const reloadModelRegistryState = async () => {
    if (modelRegistryLoadRef.current) {
      return modelRegistryLoadRef.current;
    }
    modelRegistryLoadRef.current = (async () => {
      const modelResponse = await fetchWithTimeout(
        `${BaseURL}/model-options`,
        {},
        MODEL_OPTIONS_FETCH_TIMEOUT_MS,
      );
      const modelData = await parseApiJson(modelResponse, 'Failed to load model registry settings');
      let bindingData = [];
      try {
        const bindingResponse = await fetchWithTimeout(`${BaseURL}/model-bindings`, {}, 30000);
        if (bindingResponse.ok) {
          bindingData = await parseApiJson(bindingResponse, 'Failed to load model bindings');
        }
      } catch (error) {
        console.warn('model-bindings unavailable; using model-options defaults', error);
      }
      setModelOptionCatalog(modelData || { stages: [] });
      setMountedModels(modelData?.mounted_models || {});
      const bindingList = normalizeBindingsPayload(bindingData);
      setDefaultBindings(extractDefaultBindings(bindingList, modelData));
      return { modelData, bindingData: bindingList };
    })();
    try {
      return await modelRegistryLoadRef.current;
    } finally {
      modelRegistryLoadRef.current = null;
    }
  };

  const saveDefaultBindings = async () => {
    setIsSavingBindings(true);
    try {
      const persistedMountedModelsByStage = modelOptionCatalog.mounted_models || {};
      const mountedModelsByStageForSave = MODEL_STAGE_OPTIONS.reduce((result, option) => {
        const draftKeys = mountedModels?.[option.stage];
        const persistedKeys = persistedMountedModelsByStage?.[option.stage];
        result[option.stage] = Array.isArray(draftKeys) && draftKeys.length > 0
          ? draftKeys
          : (Array.isArray(persistedKeys) ? persistedKeys : []);
        return result;
      }, {});
      const payload = MODEL_STAGE_OPTIONS.map((option) => ({
        stage: option.stage,
        model_key: resolveEffectiveDefaultKey(
          option.stage,
          defaultBindings,
          modelOptionCatalog,
          mountedModelsByStageForSave,
        ) || null,
        binding_scope: 'default',
      }));
      await fetchJson(
        `${BaseURL}/model-bindings`,
        {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(payload),
        },
        'Failed to save default model bindings',
        30000,
      );
      await reloadModelRegistryState();
      await reloadAlertRuleState({ includeRules: false, sourcesSnapshot: sources.filter((source) => source.id) });
      setBanner({ kind: 'success', text: 'Default model bindings saved.' });
    } catch (error) {
      setBanner({
        kind: 'error',
        text: formatApiError(error, 'Failed to save default model bindings.'),
      });
    } finally {
      setIsSavingBindings(false);
    }
  };

  const setStage2ProviderField = (providerKey, field, value) => {
    setStage2ProviderSettings((previous) =>
      previous.map((provider) =>
        provider.provider_key === providerKey
          ? {
              ...provider,
              [field]: value,
            }
          : provider
      )
    );
    setStage2ProviderErrors((previous) => {
      if (!previous[providerKey]) {
        return previous;
      }
      const next = { ...previous };
      delete next[providerKey];
      return next;
    });
  };

  const saveStage2Providers = async () => {
    if (!validateStage2ProviderSettings()) {
      return;
    }
    setIsSavingStage2ProviderSettings(true);
    try {
      const response = await fetch(`${BaseURL}/settings/stage2-provider-settings`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(
          stage2ProviderSettings.map((provider) => ({
            provider_key: provider.provider_key,
            display_name: provider.display_name,
            enabled: provider.enabled,
            base_url: provider.base_url,
            model_name: provider.model_name,
            timeout_seconds: Number(provider.timeout_seconds) || 30,
            auth_optional: provider.auth_optional,
            api_key: provider.api_key,
            auth_token: provider.auth_token,
          })),
        ),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveApiErrorMessage(data, 'Failed to save Stage 2 provider settings'));
      }
      const nextByKey = new Map(
        normalizeListPayload(data).map((item) => [item.provider_key, hydrateStage2ProviderSettings(item)]),
      );
      setStage2ProviderSettings(
        STAGE2_PROVIDER_OPTIONS.map((option) =>
          nextByKey.get(option.provider_key) || createStage2ProviderDraft(option.provider_key)
        ),
      );
      setBanner({ kind: 'success', text: 'Stage 2 provider settings saved.' });
    } catch (error) {
      setBanner({ kind: 'error', text: error.message });
    } finally {
      setIsSavingStage2ProviderSettings(false);
    }
  };

  const testStage2Provider = async (provider) => {
    const option = getStage2ProviderOption(provider.provider_key);
    const secretField = option?.secretField || 'api_key';
    if (provider.enabled) {
      if (!provider.base_url.trim() || !provider.model_name.trim() || (!provider.auth_optional && !String(provider[secretField] || '').trim())) {
        setStage2ProviderErrors((previous) => ({
          ...previous,
          [provider.provider_key]: 'Complete the required fields before testing this provider.',
        }));
        return;
      }
    }
    setBusyStage2ProviderTests((previous) => ({
      ...previous,
      [provider.provider_key]: true,
    }));
    try {
      const response = await fetch(`${BaseURL}/settings/stage2-provider-settings/test`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(provider),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveApiErrorMessage(data, 'Failed to test Stage 2 provider settings'));
      }
      setStage2ProviderSettings((previous) =>
        previous.map((item) =>
          item.provider_key === provider.provider_key
            ? {
                ...item,
                last_test_status: data?.last_test_status ?? (data?.ok ? 'ok' : 'error'),
                last_test_message: data?.detail ?? '',
                secret_present: Boolean(data?.secret_present),
              }
            : item
        )
      );
      setBanner({
        kind: data?.ok ? 'success' : 'error',
        text: data?.detail || `${option?.label || provider.provider_key} provider test completed.`,
      });
      await reloadStage2ProviderSettings().catch(() => {});
    } catch (error) {
      setBanner({ kind: 'error', text: error.message });
    } finally {
      setBusyStage2ProviderTests((previous) => ({
        ...previous,
        [provider.provider_key]: false,
      }));
    }
  };

  const addAnomalyItem = () => {
    setAnomalyItems((previous) => [...previous, createAnomalyItemDraft()]);
  };

  const removeAnomalyItem = (clientKey) => {
    setAnomalyItems((previous) => previous.filter((item) => item.clientKey !== clientKey));
  };

  const setAnomalyItemField = (clientKey, field, value) => {
    setAnomalyItems((previous) =>
      previous.map((item) =>
        item.clientKey === clientKey
          ? {
              ...item,
              [field]: value,
            }
          : item
      )
    );
  };

  const addAnomalyBehavior = () => {
    setAnomalyBehaviors((previous) => [...previous, createAnomalyBehaviorDraft()]);
  };

  const removeAnomalyBehavior = (clientKey) => {
    setAnomalyBehaviors((previous) => previous.filter((behavior) => behavior.clientKey !== clientKey));
  };

  const setAnomalyBehaviorField = (clientKey, value) => {
    setAnomalyBehaviors((previous) =>
      previous.map((behavior) =>
        behavior.clientKey === clientKey
          ? {
              ...behavior,
              value,
            }
          : behavior
      )
    );
  };

  const validateAnomalyPrompts = () => {
    const invalidItem = anomalyItems.find((item) => !item.item.trim());
    if (invalidItem) {
      setBanner({ kind: 'error', text: 'Each anomaly item needs a name.' });
      return false;
    }
    const invalidBehavior = anomalyBehaviors.find((behavior) => !behavior.value.trim());
    if (invalidBehavior) {
      setBanner({ kind: 'error', text: 'Each anomaly behavior needs a name.' });
      return false;
    }
    return true;
  };

  const saveAnomalyPrompts = async () => {
    if (!validateAnomalyPrompts()) {
      return;
    }
    setIsSavingAnomalyPrompts(true);
    try {
      const data = await fetchJson(
        `${BaseURL}/settings/anomaly-prompts`,
        {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            anomaly_items: anomalyItems.map((item) => ({
              item: item.item.trim(),
            })),
            anomaly_behaviors: anomalyBehaviors.map((behavior) => behavior.value.trim()).filter(Boolean),
          }),
        },
        'Failed to save anomaly prompts',
        30000,
      );
      setAnomalyItems((data.anomaly_items || []).map((item, index) => hydrateAnomalyItem(item, index)));
      setAnomalyBehaviors((data.anomaly_behaviors || []).map((item, index) => hydrateAnomalyBehavior(item, index)));
      await reloadAlertRuleState({ includeRules: false, sourcesSnapshot: sources.filter((source) => source.id) });
      setBanner({ kind: 'success', text: 'Anomaly detection config saved.' });
    } catch (error) {
      setBanner({ kind: 'error', text: formatApiError(error, 'Failed to save anomaly prompts.') });
    } finally {
      setIsSavingAnomalyPrompts(false);
    }
  };

  const loadStandardAnomalyPromptConfig = () => {
    if (!standardPromptSettings.anomaly_items?.length && !standardPromptSettings.anomaly_behaviors?.length) {
      setBanner({ kind: 'error', text: 'Standard anomaly detection config is unavailable.' });
      return;
    }
    setAnomalyItems((standardPromptSettings.anomaly_items || []).map((item, index) => hydrateAnomalyItem(item, index)));
    setAnomalyBehaviors((standardPromptSettings.anomaly_behaviors || []).map((item, index) => hydrateAnomalyBehavior(item, index)));
    setBanner({ kind: 'success', text: 'Loaded standard anomaly detection config.' });
  };

  const saveSources = async () => {
    if (!validateSources()) {
      setBanner({ kind: 'error', text: 'Fix the highlighted source rows first.' });
      return;
    }

    setIsSaving(true);
    try {
      const data = await fetchJson(
        `${BaseURL}/settings/input-sources`,
        {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(sanitizeSourcesForApi(sources)),
        },
        'Failed to save source settings',
        60000,
      );
      const hydratedSources = data.map((source, index) => hydrateSource(source, index));
      setSources(hydratedSources);
      await reloadModelRegistryState();
      await reloadAlertRuleState({ sourcesSnapshot: data });
      setBanner({
        kind: 'success',
        text: 'Source settings saved. Next: configure Rules (alert + anomaly triggers), then start a run from Run / Monitor Run.',
      });
      window.dispatchEvent(new CustomEvent(SOURCES_UPDATED_EVENT));
    } catch (error) {
      setBanner({ kind: 'error', text: formatApiError(error, 'Failed to save source settings.') });
    } finally {
      setIsSaving(false);
    }
  };

  const toggleMountedModel = (stage, modelKey, checked) => {
    setMountedModels((previous) => {
      const current = new Set(previous[stage] || []);
      if (checked) {
        current.add(modelKey);
      } else {
        current.delete(modelKey);
      }
      return {
        ...previous,
        [stage]: Array.from(current),
      };
    });
  };

  const toggleInventoryStage = (stage) => {
    setExpandedInventoryStages((previous) => ({
      ...previous,
      [stage]: !previous[stage],
    }));
  };

  const saveMountedModels = async ({ force = false } = {}) => {
    setIsSavingMountedModels(true);
    try {
      const payload = MODEL_STAGE_OPTIONS.map((option) => ({
        stage: option.stage,
        mounted_model_keys: mountedModels[option.stage] || [],
      }));
      const response = await fetch(`${BaseURL}/mounted-models${force ? '?force=true' : ''}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });
      const data = await readApiPayload(response, 'Failed to save mounted models');
      if (!response.ok) {
        const conflict = normalizeMountedModelConflict(data);
        if (conflict) {
          setMountedModelConflict(conflict);
          return;
        }
        throw new Error(resolveApiErrorMessage(data, 'Failed to save mounted models'));
      }
      setMountedModelConflict(null);
      const nextMounted = {};
      (data || []).forEach((entry) => {
        nextMounted[entry.stage] = entry.mounted_model_keys || [];
      });
      setMountedModels(nextMounted);
      await reloadModelRegistryState();
      setBanner({ kind: 'success', text: 'Mounted model inventory updated.' });
    } catch (error) {
      setBanner({ kind: 'error', text: formatApiError(error, 'Failed to save mounted models.') });
    } finally {
      setIsSavingMountedModels(false);
    }
  };

  const confirmForcedMountedModelSave = async () => {
    setMountedModelConflict(null);
    await saveMountedModels({ force: true });
  };

  const handleUpload = async (clientKey, file) => {
    if (!file) {
      return;
    }
    const validationError = validateSelectedVideoFile(file);
    if (validationError) {
      setUploadFeedback((previous) => ({
        ...previous,
        [clientKey]: { kind: 'error', text: validationError },
      }));
      setBanner({ kind: 'error', text: validationError });
      return;
    }
    setBusyUploads((previous) => ({ ...previous, [clientKey]: true }));
    setUploadFeedback((previous) => ({
      ...previous,
      [clientKey]: { kind: 'pending', text: `Uploading ${file.name}...` },
    }));
    const formData = new FormData();
    formData.append('file', file);
    try {
      const data = await fetchJson(
        `${BaseURL}/settings/input-sources/uploads`,
        {
          method: 'POST',
          body: formData,
        },
        'Failed to upload video',
        120000,
      );
      setSources((previous) =>
        previous.map((source) =>
          source.clientKey === clientKey
            ? {
                ...source,
                upload_id: data.upload.id,
                upload: data.upload,
                label: source.label || stripFileExtension(data.upload.original_filename),
              }
            : source
        )
      );
      setRowErrors((previous) => ({
        ...previous,
        [clientKey]: undefined,
      }));
      const successMessage = `Uploaded ${data.upload.original_filename} successfully.`;
      setUploadFeedback((previous) => ({
        ...previous,
        [clientKey]: { kind: 'success', text: successMessage },
      }));
      setBanner({ kind: 'success', text: successMessage });
    } catch (error) {
      const uploadError = formatApiError(error, 'Failed to upload video.');
      setUploadFeedback((previous) => ({
        ...previous,
        [clientKey]: { kind: 'error', text: uploadError },
      }));
      setBanner({ kind: 'error', text: uploadError });
    } finally {
      setBusyUploads((previous) => ({ ...previous, [clientKey]: false }));
    }
  };

  const saveAlertRules = async () => {
    if (!validateAlertRules()) {
      setBanner({ kind: 'error', text: 'Fix the alert rule rows first.' });
      return;
    }
    setIsSavingAlertRules(true);
    try {
      let response = await fetch(`${BaseURL}/settings/trigger-rules`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(sanitizeAlertRulesForApi(alertRules)),
      });
      let data = await readApiPayload(response, 'Failed to save alert rules');
      if (!response.ok || !Array.isArray(data)) {
        response = await fetch(`${BaseURL}/settings/alert-rules`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(
            alertRules
              .filter((rule) => rule.rule_kind === 'detector' && rule.source_ids.length > 0)
              .map((rule) => ({
                id: rule.id ?? undefined,
                source_id: rule.source_ids[0],
                enabled: rule.enabled,
                rule_label: rule.rule_label?.trim() || null,
                signal_family: 'detector',
                target_key: rule.target_key,
                min_confidence: Number(rule.min_confidence),
                alert_level: rule.alert_level,
              })),
          ),
        });
        data = await readApiPayload(response, 'Failed to save alert rules');
      }
      if (!response.ok) {
        throw new Error(data.detail || 'Failed to save alert rules');
      }
      const hydratedRules = (Array.isArray(data) ? data : []).map((rule, index) => hydrateAlertRule(rule, index));
      setAlertRules(hydratedRules);
      setPersistedAlertRules(hydratedRules);
      setAlertRuleErrors({});
      await reloadAlertRuleState({ includeRules: false, sourcesSnapshot: sources.filter((source) => source.id) });
      setBanner({ kind: 'success', text: 'Alert rules saved.' });
    } catch (error) {
      setBanner({ kind: 'error', text: formatApiError(error, 'Request failed.') });
    } finally {
      setIsSavingAlertRules(false);
    }
  };

  const saveTelegramSubscriptions = async () => {
    if (!validateTelegramSubscriptions()) {
      setBanner({ kind: 'error', text: 'Fix the Telegram subscription rows first.' });
      return;
    }
    setIsSavingTelegramSubscriptions(true);
    try {
      const data = await fetchJson(
        `${BaseURL}/settings/telegram-trigger-subscriptions`,
        {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(sanitizeTelegramSubscriptionsForApi(telegramSubscriptions)),
        },
        'Failed to save Telegram trigger subscriptions',
        30000,
      );
      setTelegramSubscriptions(normalizeListPayload(data).map((subscription, index) => hydrateTelegramSubscription(subscription, index)));
      setTelegramSubscriptionErrors({});
      setBanner({ kind: 'success', text: 'Telegram trigger subscriptions saved.' });
    } catch (error) {
      setBanner({ kind: 'error', text: formatApiError(error, 'Request failed.') });
    } finally {
      setIsSavingTelegramSubscriptions(false);
    }
  };

  const sendTelegramTestMessage = async (subscription) => {
    if (subscription.bot_token.trim() === MASKED_SECRET_VALUE) {
      setBanner({ kind: 'error', text: 'Bot token is masked. Paste your new token, save, then send test.' });
      return;
    }
    if (!subscription.bot_token.trim() || !subscription.chat_id.trim()) {
      setTelegramSubscriptionErrors((previous) => ({
        ...previous,
        [subscription.clientKey]: !subscription.bot_token.trim()
          ? 'Bot token is required.'
          : 'Chat ID is required.',
      }));
      setBanner({ kind: 'error', text: 'Bot token and chat ID are required for a Telegram test message.' });
      return;
    }
    setBusyTelegramTests((previous) => ({ ...previous, [subscription.clientKey]: true }));
    try {
      const data = await fetchJson(
        `${BaseURL}/settings/telegram-trigger-subscriptions/test`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            enabled: subscription.enabled,
            subscription_label: subscription.subscription_label?.trim() || null,
            bot_token: subscription.bot_token.trim(),
            chat_id: subscription.chat_id.trim(),
            send_media: Boolean(subscription.send_media),
            media_source: subscription.media_source || 'none',
          }),
        },
        'Failed to send Telegram test message',
        30000,
      );
      setBanner({ kind: 'success', text: data.detail || 'Telegram test message sent.' });
    } catch (error) {
      setBanner({ kind: 'error', text: formatApiError(error, 'Request failed.') });
    } finally {
      setBusyTelegramTests((previous) => ({ ...previous, [subscription.clientKey]: false }));
    }
  };

  const saveAppleMessageSubscriptions = async () => {
    if (!validateAppleMessageSubscriptions()) {
      setBanner({ kind: 'error', text: 'Fix the Apple Messages subscription rows first.' });
      return;
    }
    setIsSavingAppleMessageSubscriptions(true);
    try {
      const data = await fetchJson(
        `${BaseURL}/settings/apple-message-trigger-subscriptions`,
        {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(sanitizeAppleMessageSubscriptionsForApi(appleMessageSubscriptions)),
        },
        'Failed to save Apple Messages trigger subscriptions',
        30000,
      );
      setAppleMessageSubscriptions(normalizeListPayload(data).map((subscription, index) => hydrateAppleMessageSubscription(subscription, index)));
      setAppleMessageSubscriptionErrors({});
      setBanner({ kind: 'success', text: 'Apple Messages trigger subscriptions saved.' });
    } catch (error) {
      setBanner({ kind: 'error', text: formatApiError(error, 'Request failed.') });
    } finally {
      setIsSavingAppleMessageSubscriptions(false);
    }
  };

  const sendAppleMessageTest = async (subscription) => {
    if (!subscription.recipient_handle.trim()) {
      setAppleMessageSubscriptionErrors((previous) => ({
        ...previous,
        [subscription.clientKey]: 'Recipient handle is required.',
      }));
      setBanner({ kind: 'error', text: 'Recipient handle is required for an Apple Messages test message.' });
      return;
    }
    setBusyAppleMessageTests((previous) => ({ ...previous, [subscription.clientKey]: true }));
    try {
      const data = await fetchJson(
        `${BaseURL}/settings/apple-message-trigger-subscriptions/test`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            enabled: subscription.enabled,
            subscription_label: subscription.subscription_label?.trim() || null,
            recipient_handle: subscription.recipient_handle.trim(),
            service: subscription.service,
          }),
        },
        'Failed to send Apple Messages test message',
        30000,
      );
      setBanner({ kind: 'success', text: data.detail || 'Apple Messages test message sent.' });
    } catch (error) {
      setBanner({ kind: 'error', text: formatApiError(error, 'Request failed.') });
    } finally {
      setBusyAppleMessageTests((previous) => ({ ...previous, [subscription.clientKey]: false }));
    }
  };

  const testGoveeApiKey = async (endpoint) => {
    if (!endpoint.api_key.trim()) {
      setGoveeEndpointErrors((previous) => ({
        ...previous,
        [endpoint.clientKey]: 'API key is required.',
      }));
      setBanner({ kind: 'error', text: 'API key is required for a Govee test.' });
      return;
    }
    setBusyGoveeTests((previous) => ({ ...previous, [endpoint.clientKey]: true }));
    try {
      const query = endpoint.api_key.trim() === MASKED_SECRET_VALUE && endpoint.id
        ? `?endpoint_id=${endpoint.id}`
        : '';
      const data = await fetchJson(
        `${BaseURL}/settings/govee/test${query}`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ api_key: endpoint.api_key.trim() }),
        },
        'Failed to validate Govee API key',
        60000,
      );
      setBanner({ kind: 'success', text: data.message || 'Govee API key is valid.' });
    } catch (error) {
      setBanner({ kind: 'error', text: formatApiError(error, 'Request failed.') });
    } finally {
      setBusyGoveeTests((previous) => ({ ...previous, [endpoint.clientKey]: false }));
    }
  };

  const discoverGoveeDevices = async (endpoint) => {
    if (!endpoint.api_key.trim()) {
      setGoveeEndpointErrors((previous) => ({
        ...previous,
        [endpoint.clientKey]: 'API key is required.',
      }));
      setBanner({ kind: 'error', text: 'API key is required to discover Govee devices.' });
      return;
    }
    setBusyGoveeDiscovery((previous) => ({ ...previous, [endpoint.clientKey]: true }));
    try {
      const query = endpoint.api_key.trim() === MASKED_SECRET_VALUE && endpoint.id
        ? `?endpoint_id=${endpoint.id}`
        : '';
      const data = await fetchJson(
        `${BaseURL}/settings/govee/devices${query}`,
        {
          headers: endpoint.api_key.trim() === MASKED_SECRET_VALUE
            ? {}
            : {
                'x-govee-api-key': endpoint.api_key.trim(),
              },
        },
        'Failed to discover Govee devices',
        120000,
      );
      setGoveeDiscoveryResults((previous) => ({
        ...previous,
        [endpoint.clientKey]: data || [],
      }));
      setGoveeDiscoveryMessages((previous) => ({
        ...previous,
        [endpoint.clientKey]: data.length > 0
          ? `Discovered ${data.length} Govee light device${data.length === 1 ? '' : 's'}.`
          : 'The API key is valid, but no light-capable Govee devices were returned for this account.',
      }));
      setBanner({
        kind: 'success',
        text: data.length > 0
          ? `Discovered ${data.length} Govee light device${data.length === 1 ? '' : 's'}.`
          : 'Govee API key is valid, but no light-capable devices were returned.',
      });
    } catch (error) {
      setBanner({ kind: 'error', text: formatApiError(error, 'Request failed.') });
    } finally {
      setBusyGoveeDiscovery((previous) => ({ ...previous, [endpoint.clientKey]: false }));
    }
  };

  const saveGoveeEndpoints = async () => {
    if (!validateGoveeEndpoints()) {
      setBanner({ kind: 'error', text: 'Fix the Govee connection rows first.' });
      return;
    }
    setIsSavingGoveeEndpoints(true);
    try {
      const data = await fetchJson(
        `${BaseURL}/settings/govee-connector-endpoints`,
        {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(sanitizeGoveeEndpointsForApi(goveeEndpoints)),
        },
        'Failed to save Govee light connections',
        30000,
      );
      setGoveeEndpoints(normalizeListPayload(data).map((endpoint, index) => hydrateGoveeEndpoint(endpoint, index)));
      setGoveeEndpointErrors({});
      setBanner({ kind: 'success', text: 'Govee light connections saved.' });
    } catch (error) {
      setBanner({ kind: 'error', text: formatApiError(error, 'Request failed.') });
    } finally {
      setIsSavingGoveeEndpoints(false);
    }
  };

  const sendGoveeTestAction = async (endpoint) => {
    if (!validateGoveeEndpoints()) {
      setBanner({ kind: 'error', text: 'Fix the Govee connection row before sending a test action.' });
      return;
    }
    setBusyGoveeTests((previous) => ({ ...previous, [endpoint.clientKey]: true }));
    try {
      const query = endpoint.api_key.trim() === MASKED_SECRET_VALUE && endpoint.id
        ? `?endpoint_id=${endpoint.id}`
        : '';
      const data = await fetchJson(
        `${BaseURL}/settings/govee-connector-endpoints/test${query}`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(sanitizeGoveeEndpointsForApi([endpoint])[0]),
        },
        'Failed to send Govee test action',
        60000,
      );
      setBanner({ kind: 'success', text: data.detail || 'Govee trigger action sent.' });
    } catch (error) {
      setBanner({ kind: 'error', text: formatApiError(error, 'Request failed.') });
    } finally {
      setBusyGoveeTests((previous) => ({ ...previous, [endpoint.clientKey]: false }));
    }
  };

  const saveConnectorZooRepoSettings = async () => {
    setIsSavingConnectorZooRepoSettings(true);
    try {
      const data = await fetchJson(
        `${BaseURL}/settings/connector-zoo-repo`,
        {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            catalog_url: connectorZooRepoSettings.catalog_url.trim() || null,
          }),
        },
        'Failed to save Connector Zoo repo settings',
        30000,
      );
      setConnectorZooRepoSettings({
        catalog_url: data?.catalog_url ?? '',
      });
      await reloadRepoConnectorZooCatalog();
      setBanner({ kind: 'success', text: 'Connector Zoo catalog settings updated.' });
    } catch (error) {
      setBanner({ kind: 'error', text: formatApiError(error, 'Request failed.') });
    } finally {
      setIsSavingConnectorZooRepoSettings(false);
    }
  };

  const installRepoConnector = async (connectorKey) => {
    setInstallingRepoConnectorKey(connectorKey);
    try {
      const data = await fetchJson(
        `${BaseURL}/connector-zoo/repo/install`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ connector_key: connectorKey }),
        },
        'Failed to add connector from Connector Zoo',
        120000,
      );
      await Promise.all([
        reloadGenericConnectorEndpointState(),
        reloadGoveeEndpointState(),
        reloadRepoConnectorZooCatalog(),
      ]);
      setConnectorSubTab('connections');
      setBanner({
        kind: 'success',
        text: data.message || 'Connector added. Restart Hearthlight to activate the plugin runtime.',
      });
    } catch (error) {
      setBanner({ kind: 'error', text: formatApiError(error, 'Request failed.') });
    } finally {
      setInstallingRepoConnectorKey('');
    }
  };

  const modelOptionsByStage = MODEL_STAGE_OPTIONS.reduce((result, option) => {
    const stageEntry = (modelOptionCatalog.stages || []).find((entry) => entry.stage === option.stage);
    result[option.stage] = stageEntry?.options || [];
    return result;
  }, {});
  const modelDisplayNamesByStage = MODEL_STAGE_OPTIONS.reduce((result, option) => {
    result[option.stage] = (modelOptionsByStage[option.stage] || []).reduce((map, registration) => {
      map[registration.model_key] = registration.display_name || registration.model_key;
      return map;
    }, {});
    return result;
  }, {});
  const getEffectiveDefaultKey = (stage) => resolveEffectiveDefaultKey(
    stage,
    defaultBindings,
    modelOptionCatalog,
    mountedModelsByStage,
  );

  const getDisplayNameForStage = (stage, modelKey, fallbackLabel) => {
    const effectiveKey = modelKey || getEffectiveDefaultKey(stage);
    if (!effectiveKey) {
      return fallbackLabel;
    }
    return modelDisplayNamesByStage[stage]?.[effectiveKey] || effectiveKey;
  };
  const detectionRules = alertRules.filter((rule) => rule.rule_kind === 'detector');
  const anomalyRules = alertRules.filter((rule) => rule.rule_kind === 'anomaly');
  const modelZooSource = modelOptionCatalog.model_zoo || {};
  const persistedMountedModelsByStage = modelOptionCatalog.mounted_models || {};
  const mountedModelsByStage = MODEL_STAGE_OPTIONS.reduce((result, option) => {
    const draftKeys = mountedModels?.[option.stage];
    const persistedKeys = persistedMountedModelsByStage?.[option.stage];
    result[option.stage] = Array.isArray(draftKeys) && draftKeys.length > 0
      ? draftKeys
      : (Array.isArray(persistedKeys) ? persistedKeys : []);
    return result;
  }, {});
  const modelZooSummary = modelZooSource.commit_short
    ? `Options prepared from model-zoo commit ${modelZooSource.commit_short}${modelZooSource.resolved_from ? ` via ${modelZooSource.resolved_from.replace('_', ' ')}` : ''}.`
    : 'Options prepared from the installed model-zoo catalog.';
  const isTelegramConnectorConfigured = telegramSubscriptions.some(
    (subscription) => subscription.enabled && subscription.bot_token.trim() && subscription.chat_id.trim(),
  );
  const isAppleMessagesConnectorConfigured = appleMessageSubscriptions.some(
    (subscription) =>
      subscription.enabled
      && subscription.recipient_handle.trim()
      && ['iMessage', 'SMS'].includes(subscription.service),
  );
  const isGoveeConnectorConfigured = goveeEndpoints.some(
    (endpoint) =>
      endpoint.enabled
      && endpoint.sku
      && endpoint.device
      && endpoint.capability_type
      && endpoint.capability_instance
      && endpoint.api_key.trim(),
  );
  const repoConnectorEntries = Array.isArray(repoConnectorZooCatalog.connectors)
    ? repoConnectorZooCatalog.connectors
    : [];
  const genericInstalledConnectorEndpoints = genericConnectorEndpoints.filter(
    (endpoint) => endpoint.connector_key !== 'govee',
  );
  const alertRuleConnectorTargets = [
    ...telegramSubscriptions
      .filter((subscription) => subscription.id && subscription.enabled)
      .map((subscription, index) => ({
        id: Number(subscription.id),
        label: subscription.subscription_label?.trim() || `Telegram ${index + 1}`,
        description: `Telegram · ${subscription.chat_id || 'configured chat'}`,
      })),
    ...appleMessageSubscriptions
      .filter((subscription) => subscription.id && subscription.enabled)
      .map((subscription, index) => ({
        id: Number(subscription.id),
        label: subscription.subscription_label?.trim() || `Apple Messages ${index + 1}`,
        description: `Apple Messages · ${subscription.recipient_handle || subscription.service}`,
      })),
    ...goveeEndpoints
      .filter((endpoint) => endpoint.id && endpoint.enabled && endpoint.resolved !== false)
      .map((endpoint, index) => ({
        id: Number(endpoint.id),
        label: endpoint.label?.trim() || endpoint.device_name || `Govee ${index + 1}`,
        description: `Govee · ${endpoint.device_name || endpoint.device || 'configured light'}`,
      })),
    ...genericInstalledConnectorEndpoints
      .filter((endpoint) => endpoint.id && endpoint.enabled && endpoint.resolved !== false)
      .map((endpoint, index) => ({
        id: Number(endpoint.id),
        label: endpoint.label?.trim() || `${endpoint.connector_key.replaceAll('_', ' ')} ${index + 1}`,
        description: `${endpoint.connector_key.replaceAll('_', ' ')}`,
      })),
  ];
  const alertRuleConnectorTargetsById = alertRuleConnectorTargets.reduce((result, connector) => {
    result[connector.id] = connector;
    return result;
  }, {});
  const stageLibraryEntries = MODEL_STAGE_OPTIONS.map((option) => {
    const stageOptions = modelOptionsByStage[option.stage] || [];
    const mountedCount = (mountedModelsByStage[option.stage] || []).length;
    return {
      ...option,
      ...MODEL_STAGE_COPY[option.stage],
      options: stageOptions,
      mountedCount,
      defaultDisplayName: getDisplayNameForStage(option.stage, defaultBindings[option.stage], 'No default selected'),
    };
  });
  const stage2ModelOptions = modelOptionsByStage.anomaly_stage_2 || [];
  const currentDefaultStage2ModelKey = defaultBindings.anomaly_stage_2 || '';
  const currentDefaultStage2Model = stage2ModelOptions.find(
    (option) => option.model_key === currentDefaultStage2ModelKey,
  ) || null;
  const currentDefaultStage2ProviderProfile = STAGE2_PROVIDER_OPTIONS.find((option) =>
    option.runtimeProviders.includes(currentDefaultStage2Model?.runtime?.provider)
  ) || null;
  const stage2ProviderUsageByKey = STAGE2_PROVIDER_OPTIONS.reduce((result, option) => {
    result[option.provider_key] = stage2ModelOptions.filter((modelOption) =>
      option.runtimeProviders.includes(modelOption?.runtime?.provider)
    );
    return result;
  }, {});
  const mountedModelChanges = MODEL_STAGE_OPTIONS.reduce(
    (result, option) => {
      const persistedSet = new Set(persistedMountedModelsByStage[option.stage] || []);
      const draftSet = new Set(mountedModelsByStage[option.stage] || []);
      for (const modelKey of draftSet) {
        if (!persistedSet.has(modelKey)) {
          result.added += 1;
        }
      }
      for (const modelKey of persistedSet) {
        if (!draftSet.has(modelKey)) {
          result.removed += 1;
        }
      }
      return result;
    },
    { added: 0, removed: 0 },
  );
  const hasMountedModelChanges = mountedModelChanges.added > 0 || mountedModelChanges.removed > 0;
  const mountedModelActionLabel = hasMountedModelChanges ? 'Remount Models' : 'Mount Models';
  const mountedModelProgressLabel = mountedModelChanges.added > 0 && mountedModelChanges.removed > 0
    ? 'Remounting models...'
    : mountedModelChanges.removed > 0
      ? 'Dismounting models...'
      : 'Mounting models...';
  const mountedModelConflictEntries = mountedModelConflict
    ? Object.entries(mountedModelConflict.in_use_models || {})
    : [];
  const renderTabSection = (tabKey, content) => {
    if (forcedTab) {
      return activeTab === tabKey ? content : null;
    }
    return (
      <div
        key={`settings-section-${tabKey}`}
        style={{ display: activeTab === tabKey ? 'block' : 'none' }}
        aria-hidden={activeTab === tabKey ? 'false' : 'true'}
      >
        {content}
      </div>
    );
  };
  const getProcessingRateGuidance = (option) => {
    if (option.stage === 'detector') {
      return option.requires_gpu ? 'Moderate' : 'Heavy';
    }
    if (option.stage === 'tracker') {
      return 'Lightweight';
    }
    if (option.stage === 'anomaly_stage_1') {
      return 'Lightweight';
    }
    return option.requires_gpu ? 'Moderate' : 'Heavy';
  };

  const renderMountedModelOptions = (stage) => {
    const stageOptions = modelOptionsByStage[stage] || [];
    const mountedKeys = new Set(mountedModelsByStage[stage] || []);
    const mountedOptions = stageOptions.filter((option) => mountedKeys.has(option.model_key));
    if (mountedOptions.length === 0) {
      return null;
    }
    return (
      <optgroup label="Mounted">
        {mountedOptions.map((registration) => (
          <option key={registration.model_key} value={registration.model_key}>
            {registration.display_name || registration.model_key}
          </option>
        ))}
      </optgroup>
    );
  };

  const renderDefaultBindingOptions = (stage) => {
    const stageOptions = modelOptionsByStage[stage] || [];
    const currentKey = getEffectiveDefaultKey(stage);
    const mountedOptions = stageOptions.filter(
      (option) => (mountedModelsByStage[stage] || []).includes(option.model_key),
    );
    const mountedKeySet = new Set(mountedOptions.map((option) => option.model_key));
    const savedDefaultOption = currentKey && !mountedKeySet.has(currentKey)
      ? stageOptions.find((option) => option.model_key === currentKey)
      : null;

    return (
      <>
        <option value="">No default</option>
        {savedDefaultOption && (
          <option value={savedDefaultOption.model_key}>
            {savedDefaultOption.display_name || savedDefaultOption.model_key}
          </option>
        )}
        {renderMountedModelOptions(stage)}
      </>
    );
  };

  const renderModelOptions = (stage) => (
    <>
      {renderMountedModelOptions(stage)}
    </>
  );

  const getSourceDisplayName = (sourceId) => {
    const sourceIndex = sources.findIndex((source) => source.id === sourceId);
    if (sourceIndex < 0) {
      return `Source ${sourceId}`;
    }
    const source = sources[sourceIndex];
    return source.label?.trim() || defaultSourceLabel(source, sourceIndex, sources);
  };

  const formatAlertRuleConnectorSummary = (deliveryTargetIds) => {
    const labels = (deliveryTargetIds || [])
      .map((targetId) => alertRuleConnectorTargetsById[Number(targetId)]?.label)
      .filter(Boolean);
    return labels.length > 0 ? labels.join(', ') : 'No connectors selected';
  };

  return (
    <div className="settings-container">
      {mountedModelConflict && (
        <div className="settings-modal-backdrop" role="presentation">
          <div
            className="settings-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="mounted-model-conflict-title"
          >
            <div className="settings-modal-header">
              <div>
                <h3 id="mounted-model-conflict-title">Models Currently In Use</h3>
                <p className="settings-modal-subtitle">
                  {mountedModelConflict.active_run
                    ? 'Removing these models will stop the current run and clear any bindings that still point at them.'
                    : 'Removing these models will clear any default or camera bindings that still point at them.'}
                </p>
              </div>
            </div>
            <div className="settings-modal-body">
              <p>{mountedModelConflict.message}</p>
              {mountedModelConflictEntries.length > 0 && (
                <div className="settings-modal-section">
                  <span className="settings-modal-label">Models to remove</span>
                  <ul className="settings-modal-list">
                    {mountedModelConflictEntries.map(([stage, modelKeys]) => (
                      <li key={`mounted-model-conflict-${stage}`}>
                        <strong>{MODEL_STAGE_OPTIONS.find((option) => option.stage === stage)?.label || stage}</strong>
                        <span>{Array.isArray(modelKeys) ? modelKeys.join(', ') : String(modelKeys)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
            <div className="control-actions settings-modal-actions">
              <button
                type="button"
                className="ghost-button"
                onClick={() => setMountedModelConflict(null)}
                disabled={isSavingMountedModels}
              >
                Cancel
              </button>
              <button
                type="button"
                className="stop-button"
                onClick={confirmForcedMountedModelSave}
                disabled={isSavingMountedModels}
              >
                {isSavingMountedModels ? 'Stopping and Removing...' : 'Stop and Remove Models'}
              </button>
            </div>
          </div>
        </div>
      )}
      <div className="settings-content">
        <div className="panel-header">
          <div>
            <h2>{pageTitle}</h2>
            <p className="panel-subtitle">
              {pageSubtitle}
            </p>
          </div>
        </div>
        {!hideTabBar && (
          <div className="settings-tab-bar" role="tablist" aria-label="Settings sections">
            {SETTINGS_TABS.map((tab) => (
              <button
                key={tab.key}
                type="button"
                role="tab"
                aria-selected={activeTab === tab.key}
                className={`settings-tab-button ${activeTab === tab.key ? 'settings-tab-button-active' : ''}`}
                onClick={() => setSearchParams({ tab: tab.key })}
              >
                {tab.label}
              </button>
            ))}
          </div>
        )}

        <div className="settings-tab-panel">
          {renderTabSection('sources', (
            <>
              {banner && (
                <div className={`banner banner-${banner.kind}`}>
                  {banner.text}
                </div>
              )}

              <section className="control-grid">
                <div className="control-column">
                  <div className="card">
                    <div className="card-header">
                      <div>
                        <h3>Input Sources</h3>
                        <p>Manage source configuration without changing the runtime source type.</p>
                      </div>
                      <div className="button-row">
                        {SOURCE_KIND_OPTIONS.map((option) => (
                          <button
                            key={`add-${option.value}`}
                            type="button"
                            onClick={() => addSource(option.value)}
                            className="secondary-button"
                          >
                            {`Add ${option.label}`}
                          </button>
                        ))}
                      </div>
                    </div>

                    <div className="source-list">
                      {sources.map((source, index) => (
                        <div key={source.clientKey} className="source-row">
                          <div className="source-row-header">
                            <strong>{source.label.trim() || defaultSourceLabel(source, index, sources)}</strong>
                            <button
                              type="button"
                              onClick={() => removeSource(source.clientKey)}
                              className="ghost-button"
                            >
                              Remove
                            </button>
                          </div>

                          <div className="source-grid">
                            <div className="readonly-field">
                              <span>Type</span>
                              <strong>{normalizeSourceKindLabel(source.kind)}</strong>
                            </div>

                            <label>
                              <span>Label</span>
                              <input
                                type="text"
                                value={source.label}
                                onChange={(event) => setSourceField(source.clientKey, 'label', event.target.value)}
                                placeholder={defaultSourceLabel(source, index, sources)}
                              />
                            </label>

                            {source.kind === 'video_upload' ? (
                              <label className="upload-field">
                                <span>Video Upload</span>
                                <input
                                  type="file"
                                  accept={VIDEO_UPLOAD_ACCEPT}
                                  onChange={(event) => {
                                    handleUpload(source.clientKey, event.target.files?.[0]);
                                    event.target.value = '';
                                  }}
                                />
                                <small>
                                  {busyUploads[source.clientKey]
                                    ? 'Uploading...'
                                    : formatUploadedVideoSummary(source.upload)}
                                </small>
                                <small className="muted-text">Accepted video types: {SUPPORTED_VIDEO_LABEL}</small>
                                {uploadFeedback[source.clientKey] && (
                                  <div className={`upload-feedback upload-feedback-${uploadFeedback[source.clientKey].kind}`}>
                                    {uploadFeedback[source.clientKey].text}
                                  </div>
                                )}
                              </label>
                            ) : (
                              <label>
                                <span>{source.kind === 'webcam' ? 'Device Index' : 'Source Value'}</span>
                                <input
                                  type={source.kind === 'webcam' ? 'number' : 'text'}
                                  value={source.source_value ?? ''}
                                  onChange={(event) => setSourceField(
                                    source.clientKey,
                                    'source_value',
                                    source.kind === 'webcam' ? Number(event.target.value) : event.target.value,
                                  )}
                                  placeholder={sourcePlaceholder(source.kind)}
                                />
                              </label>
                            )}

                            <label>
                              <span>Frame Processing</span>
                              <select
                                value={source.kind === 'video_upload' ? 'frame_skip' : (source.frame_processing_mode || 'frame_skip')}
                                onChange={(event) => setSourceField(source.clientKey, 'frame_processing_mode', event.target.value)}
                                disabled={source.kind === 'video_upload'}
                              >
                                {FRAME_PROCESSING_MODE_OPTIONS.map((option) => (
                                  <option key={option.value} value={option.value}>
                                    {option.label}
                                  </option>
                                ))}
                              </select>
                            </label>

                            {source.kind !== 'video_upload' && (source.frame_processing_mode || 'frame_skip') === 'target_frame_rate' ? (
                              <label>
                                <span>Target Frame Rate</span>
                                <input
                                  type="number"
                                  min="0.1"
                                  step="0.1"
                                  value={source.target_frame_rate ?? 5}
                                  onChange={(event) => setSourceField(source.clientKey, 'target_frame_rate', Number(event.target.value) || 5)}
                                />
                                <small className="muted-text">Aim to process at this many frames per second.</small>
                              </label>
                            ) : (
                              <label>
                                <span>Frame Skip</span>
                                <input
                                  type="number"
                                  min="1"
                                  step="1"
                                  value={source.process_every_n_frames ?? 1}
                                  onChange={(event) => setSourceField(source.clientKey, 'process_every_n_frames', Number(event.target.value) || 1)}
                                />
                                <small className="muted-text">`1` means every frame, `3` means every 3rd frame.</small>
                              </label>
                            )}
                            <div className="readonly-field">
                              <span>Current Processing Plan</span>
                              <strong>{describeFrameProcessingMode(source)}</strong>
                              <small className="muted-text">Used when this source is started from Monitor Run.</small>
                            </div>
                          </div>

                          <div className="source-always-enabled-note">
                            Video AI is always active for configured sources. Start and stop the source itself from Monitor Run.
                          </div>

                          <div className="model-binding-grid">
                            {MODEL_STAGE_OPTIONS.map((option) => (
                              <label key={`${source.clientKey}-${option.stage}`}>
                                <span>{option.label} Override</span>
                                <select
                                  value={source[option.field] || ''}
                                  onChange={(event) => setSourceField(source.clientKey, option.field, event.target.value || null)}
                                >
                                  <option value="">
                                    Use default ({getDisplayNameForStage(option.stage, getEffectiveDefaultKey(option.stage), 'None')})
                                  </option>
                                  {renderModelOptions(option.stage)}
                                </select>
                              </label>
                            ))}
                          </div>

                          {rowErrors[source.clientKey] && (
                            <div className="row-error">{rowErrors[source.clientKey]}</div>
                          )}
                        </div>
                      ))}
                    </div>

                    <div className="control-actions">
                      <button type="button" onClick={saveSources} className="secondary-button" disabled={isSaving}>
                        {isSaving ? (
                          <>
                            <span className="button-spinner" aria-hidden="true" />
                            Updating Source Settings...
                          </>
                        ) : 'Update Source Settings'}
                      </button>
                    </div>
                  </div>
                </div>

                <div className="control-column">
                  <div className="card">
                    <div className="card-header">
                      <div>
                        <h3>Default Model Bindings</h3>
                        <p>Set default detector, tracker, Heuristic Filter, and anomaly detection models for new runs.</p>
                        <p className="muted-text">{modelZooSummary}</p>
                        <p className="muted-text">Defaults and camera overrides can only use models that are already mounted in Model Inventory.</p>
                        <p className="muted-text">
                          Saved defaults:
                          {' '}
                          {MODEL_STAGE_OPTIONS.map((option) => (
                            `${option.label}: ${getDisplayNameForStage(option.stage, getEffectiveDefaultKey(option.stage), 'No default')}`
                          )).join(' · ')}
                        </p>
                      </div>
                    </div>
                    <div className="model-binding-grid">
                      {MODEL_STAGE_OPTIONS.map((option) => (
                        <label key={option.stage}>
                          <span>{option.label}</span>
                          <select
                            value={getEffectiveDefaultKey(option.stage) || ''}
                            onChange={(event) => setDefaultBindings((previous) => ({
                              ...previous,
                              [option.stage]: event.target.value,
                            }))}
                          >
                            {renderDefaultBindingOptions(option.stage)}
                          </select>
                        </label>
                      ))}
                    </div>
                    <div className="control-actions">
                      <button
                        type="button"
                        onClick={saveDefaultBindings}
                        className="secondary-button"
                        disabled={isSavingBindings}
                      >
                        {isSavingBindings ? 'Saving...' : 'Save Default Bindings'}
                      </button>
                    </div>
                  </div>

                  <div className="card">
                    <div className="card-header">
                      <div>
                        <h3>Stage 2 Provider Settings</h3>
                        <p>Manage external anomaly detection provider endpoints, model overrides, timeouts, and encrypted credentials.</p>
                        <p className="muted-text">
                          The selected Stage 2 model still comes from Default Model Bindings. These provider profiles only control runtime connectivity for external Stage 2 adapters.
                        </p>
                      </div>
                    </div>
                    <div className="source-list">
                      <div className="source-row">
                        <div className="source-row-header">
                          <div>
                            <strong>Current Stage 2 Binding</strong>
                            <div className="muted-text">
                              {currentDefaultStage2Model
                                ? `${currentDefaultStage2Model.display_name || currentDefaultStage2Model.model_key} (${currentDefaultStage2Model.model_key})`
                                : 'No default Stage 2 model is currently selected.'}
                            </div>
                          </div>
                          <span className="model-library-badge">
                            {currentDefaultStage2ProviderProfile
                              ? `Uses ${currentDefaultStage2ProviderProfile.label}`
                              : 'No managed provider profile'}
                          </span>
                        </div>
                        <div className="muted-text">
                          {currentDefaultStage2ProviderProfile
                            ? 'Change provider credentials here without moving the Stage 2 binding away from its current model key.'
                            : 'Prompt-only or local models do not require a secure external provider profile.'}
                        </div>
                      </div>

                      {stage2ProviderSettings.map((provider) => {
                        const option = getStage2ProviderOption(provider.provider_key);
                        const secretField = option?.secretField || 'api_key';
                        const providerModels = stage2ProviderUsageByKey[provider.provider_key] || [];
                        const hasLastTest = Boolean(provider.last_test_status || provider.last_test_message || provider.last_tested_at);
                        return (
                          <div key={`stage2-provider-${provider.provider_key}`} className="source-row">
                            <div className="source-row-header">
                              <div>
                                <strong>{option?.label || provider.display_name || provider.provider_key}</strong>
                                <div className="muted-text">
                                  {providerModels.length > 0
                                    ? `Used by: ${formatListLabel(providerModels.map((item) => item.display_name || item.model_key))}`
                                    : 'Supported secure provider profile for external Stage 2 routing.'}
                                </div>
                              </div>
                              <div className="button-row">
                                {currentDefaultStage2ProviderProfile?.provider_key === provider.provider_key && (
                                  <span className="model-library-badge">Current default</span>
                                )}
                                <button
                                  type="button"
                                  className="secondary-button"
                                  onClick={() => testStage2Provider(provider)}
                                  disabled={Boolean(busyStage2ProviderTests[provider.provider_key])}
                                >
                                  {busyStage2ProviderTests[provider.provider_key] ? 'Testing...' : 'Test Connection'}
                                </button>
                              </div>
                            </div>

                            <div className="model-binding-grid">
                              <label className="toggle-field">
                                <span>Enabled</span>
                                <input
                                  type="checkbox"
                                  checked={provider.enabled}
                                  onChange={(event) => setStage2ProviderField(provider.provider_key, 'enabled', event.target.checked)}
                                />
                              </label>
                              <label>
                                <span>Base URL</span>
                                <input
                                  type="text"
                                  value={provider.base_url}
                                  onChange={(event) => setStage2ProviderField(provider.provider_key, 'base_url', event.target.value)}
                                  placeholder={provider.provider_key === 'lm_studio' ? 'http://localhost:1234/v1' : 'https://provider.example/v1'}
                                />
                              </label>
                              <label>
                                <span>Model Name</span>
                                <input
                                  type="text"
                                  value={provider.model_name}
                                  onChange={(event) => setStage2ProviderField(provider.provider_key, 'model_name', event.target.value)}
                                  placeholder="Model override"
                                />
                              </label>
                              <label>
                                <span>Timeout (seconds)</span>
                                <input
                                  type="number"
                                  min="1"
                                  max="300"
                                  step="1"
                                  value={provider.timeout_seconds}
                                  onChange={(event) => setStage2ProviderField(provider.provider_key, 'timeout_seconds', event.target.value)}
                                />
                              </label>
                              <label>
                                <span>{option?.secretLabel || 'Credential'}</span>
                                <input
                                  type="password"
                                  value={provider[secretField] ?? ''}
                                  onChange={(event) => setStage2ProviderField(provider.provider_key, secretField, event.target.value)}
                                  placeholder={provider.secret_present ? MASKED_SECRET_VALUE : `${option?.secretLabel || 'Credential'}${provider.auth_optional ? ' (optional)' : ''}`}
                                />
                                <small className="muted-text">
                                  {provider.auth_optional
                                    ? 'Leave blank to omit the auth header entirely.'
                                    : 'Leave the masked value unchanged to preserve the saved secret.'}
                                </small>
                              </label>
                              <div className="readonly-field">
                                <span>Secret Status</span>
                                <strong>{provider.secret_present ? 'Stored securely' : 'Not stored'}</strong>
                                <small className="muted-text">
                                  Saved secrets are encrypted before they are written to the control database.
                                </small>
                              </div>
                              <div className="readonly-field">
                                <span>Last Test</span>
                                <strong>
                                  {provider.last_test_status
                                    ? provider.last_test_status === 'ok'
                                      ? 'Passed'
                                      : 'Failed'
                                    : 'Not run'}
                                </strong>
                                <small className="muted-text">
                                  {hasLastTest
                                    ? `${provider.last_test_message || 'No detail'}${provider.last_tested_at ? ` · ${provider.last_tested_at}` : ''}`
                                    : 'Run a connection test to verify endpoint, model, and credential wiring.'}
                                </small>
                              </div>
                            </div>

                            {stage2ProviderErrors[provider.provider_key] && (
                              <div className="row-error">{stage2ProviderErrors[provider.provider_key]}</div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                    <div className="control-actions">
                      <button
                        type="button"
                        onClick={saveStage2Providers}
                        className="secondary-button"
                        disabled={isSavingStage2ProviderSettings}
                      >
                        {isSavingStage2ProviderSettings ? 'Saving...' : 'Save Stage 2 Provider Settings'}
                      </button>
                    </div>
                  </div>

                  <div className="card">
                    <div className="card-header">
                      <div>
                        <h3>Anomaly Prompt Settings</h3>
                        <p>Manage anomaly detection config as structured anomaly items and anomaly behaviors. The prompt template stays hidden in the prompt config file.</p>
                      </div>
                    </div>
                    <div className="source-list">
                      <div className="source-row">
                        <div className="source-row-header">
                          <strong>Anomaly Items</strong>
                          <button
                            type="button"
                            onClick={addAnomalyItem}
                            className="secondary-button"
                          >
                            Add Item
                          </button>
                        </div>
                        {anomalyItems.length === 0 ? (
                          <div className="empty-state">No anomaly items configured yet.</div>
                        ) : (
                          <>
                            <div className="anomaly-item-list">
                              {anomalyItems.map((item, index) => (
                                <div key={item.clientKey} className="anomaly-item-row">
                                  <span className="anomaly-item-index">{index + 1}</span>
                                  <input
                                    type="text"
                                    value={item.item}
                                    onChange={(event) => setAnomalyItemField(item.clientKey, 'item', event.target.value)}
                                    placeholder="weapon"
                                    className="anomaly-item-input"
                                    aria-label={`Anomaly item ${index + 1}`}
                                  />
                                  <button
                                    type="button"
                                    onClick={() => removeAnomalyItem(item.clientKey)}
                                    className="anomaly-item-remove"
                                    aria-label={`Remove anomaly item ${index + 1}`}
                                    title="Remove anomaly item"
                                  >
                                    ×
                                  </button>
                                </div>
                              ))}
                            </div>
                            <div className="compact-list-actions">
                              <button
                                type="button"
                                onClick={addAnomalyItem}
                                className="secondary-button"
                              >
                                Add Item
                              </button>
                            </div>
                          </>
                        )}
                      </div>

                      <div className="source-row">
                        <div className="source-row-header">
                          <strong>Anomaly Behaviors</strong>
                          <button
                            type="button"
                            onClick={addAnomalyBehavior}
                            className="secondary-button"
                          >
                            Add Behavior
                          </button>
                        </div>
                        {anomalyBehaviors.length === 0 ? (
                          <div className="empty-state">No anomaly behaviors configured yet.</div>
                        ) : (
                          <>
                            <div className="anomaly-item-list">
                              {anomalyBehaviors.map((behavior, index) => (
                                <div key={behavior.clientKey} className="anomaly-item-row">
                                  <span className="anomaly-item-index">{index + 1}</span>
                                  <input
                                    type="text"
                                    value={behavior.value}
                                    onChange={(event) => setAnomalyBehaviorField(behavior.clientKey, event.target.value)}
                                    placeholder="running away"
                                    className="anomaly-item-input"
                                    aria-label={`Anomaly behavior ${index + 1}`}
                                  />
                                  <button
                                    type="button"
                                    onClick={() => removeAnomalyBehavior(behavior.clientKey)}
                                    className="anomaly-item-remove"
                                    aria-label={`Remove anomaly behavior ${index + 1}`}
                                    title="Remove anomaly behavior"
                                  >
                                    ×
                                  </button>
                                </div>
                              ))}
                            </div>
                            <div className="compact-list-actions">
                              <button
                                type="button"
                                onClick={addAnomalyBehavior}
                                className="secondary-button"
                              >
                                Add Behavior
                              </button>
                            </div>
                          </>
                        )}
                      </div>
                    </div>
                    <div className="control-actions">
                      <button
                        type="button"
                        onClick={loadStandardAnomalyPromptConfig}
                        className="secondary-button"
                        disabled={!standardPromptSettings.anomaly_items?.length && !standardPromptSettings.anomaly_behaviors?.length}
                      >
                        Use Standard Anomaly Detection Config
                      </button>
                      <button
                        type="button"
                        onClick={saveAnomalyPrompts}
                        className="secondary-button"
                        disabled={isSavingAnomalyPrompts}
                      >
                        {isSavingAnomalyPrompts ? 'Saving...' : 'Save Anomaly Detection Config'}
                      </button>
                    </div>
                  </div>

                  <div className="card">
                    <div className="card-header">
                      <div>
                        <h3>Integration Endpoint</h3>
                        <p>Other systems can append a source directly.</p>
                      </div>
                    </div>
                    <div className="empty-state endpoint-info">
                      <strong>POST {`${BaseURL}/settings/input-sources`}</strong>
                      <div className="muted-text">
                        Send an `InputSource` JSON payload to add a camera stream, webcam, or uploaded video reference.
                      </div>
                      <div className="muted-text">GET {`${BaseURL}/models`}</div>
                      <div className="muted-text">GET {`${BaseURL}/model-options`}</div>
                      <div className="muted-text">GET/PUT {`${BaseURL}/model-bindings`}</div>
                      <div className="muted-text">GET/PUT {`${BaseURL}/settings/stage2-provider-settings`}</div>
                      <div className="muted-text">POST {`${BaseURL}/settings/stage2-provider-settings/test`}</div>
                      <div className="muted-text">GET/PUT {`${BaseURL}/settings/anomaly-prompts`}</div>
                      <div className="muted-text">The anomaly detection prompt template is managed in `shared/prompts/stage2_prompt_config.yaml`.</div>
                    </div>
                  </div>

                  <div className="card">
                    <div className="card-header">
                      <div>
                        <h3>Upload Endpoint</h3>
                        <p>Stage video before attaching it to a source.</p>
                      </div>
                    </div>
                    <div className="empty-state endpoint-info">
                      <strong>POST {`${BaseURL}/settings/input-sources/uploads`}</strong>
                      <div className="muted-text">
                        Upload multipart video and use the returned `upload.id` as `upload_id` when adding a `video_upload` source.
                      </div>
                    </div>
                  </div>
                </div>
              </section>
            </>
          ))}

          {renderTabSection('model-library', (
            <>
              {banner && (
                <div className={`banner banner-${banner.kind}`}>
                  {banner.text}
                </div>
              )}

              <section className="control-grid">
                <div className="control-column">
                  <div className="settings-subtabs">
                    {MODEL_LIBRARY_SUB_TABS.map((tab) => (
                      <button
                        key={tab.key}
                        type="button"
                        className={`settings-subtab ${modelLibrarySubTab === tab.key ? 'active' : ''}`}
                        onClick={() => setModelLibrarySubTab(tab.key)}
                      >
                        {tab.label}
                      </button>
                    ))}
                  </div>

                  {modelLibrarySubTab === 'inventory' && (
                    <div className="card">
                      <div className="card-header">
                        <div>
                          <h3>Model Inventory</h3>
                          <p>Mount models centrally before deployment. Cameras can only run from this shared inventory.</p>
                          <p className="muted-text">You can keep multiple models mounted per stage, including local or third-party registry entries.</p>
                        </div>
                      </div>

                      <div className="model-library-stage-list">
                        {stageLibraryEntries.map((stage) => {
                          const mountedKeys = new Set(mountedModelsByStage[stage.stage] || []);
                          const mountedOptions = stage.options.filter((option) => mountedKeys.has(option.model_key));
                          const isExpanded = Boolean(expandedInventoryStages[stage.stage]);
                          const visibleOptions = isExpanded ? stage.options : mountedOptions;
                          return (
                            <div key={`mounted-${stage.stage}`} className="model-library-stage">
                              <div className="source-row-header">
                                <div>
                                  <strong>{stage.title || stage.label}</strong>
                                  <div className="muted-text">
                                    {stage.mountedCount} mounted · {stage.options.length} available
                                  </div>
                                </div>
                                <button
                                  type="button"
                                  className="ghost-button"
                                  onClick={() => toggleInventoryStage(stage.stage)}
                                >
                                  {isExpanded ? 'Hide available models' : 'Show mounted and available models'}
                                </button>
                              </div>
                              {visibleOptions.length === 0 ? (
                                <div className="empty-state">No mounted models yet for this stage.</div>
                              ) : (
                                <div className="model-library-grid">
                                  {visibleOptions.map((option) => {
                                    const isMounted = mountedKeys.has(option.model_key);
                                    const detectorClasses = getModelClasses(option);
                                    const runtimeTargets = getRuntimeTargets(option);
                                    const backend = option.runtime?.backend || option.runtime?.tracker_name || option.runtime?.person_strategy || option.runtime?.package || null;
                                    const canToggle = !isMounted || isExpanded;
                                    return (
                                      <label
                                        key={`mounted-option-${option.model_key}`}
                                        className={`model-mount-toggle ${isMounted && !isExpanded ? 'model-mount-toggle-locked' : ''}`}
                                      >
                                        <input
                                          type="checkbox"
                                          checked={isMounted}
                                          disabled={!canToggle}
                                          onChange={(event) => toggleMountedModel(stage.stage, option.model_key, event.target.checked)}
                                          title={!canToggle ? 'Expand this stage to unmount a model that is currently mounted.' : undefined}
                                        />
                                        <span className="model-mount-toggle-body">
                                          <span className="model-mount-toggle-title">
                                            {option.display_name || option.model_key}
                                            {isMounted ? ' · Mounted' : ' · Available'}
                                          </span>
                                          {isExpanded && (
                                            <span className="model-mount-toggle-meta">
                                              <span>{describeModelFit(option)}</span>
                                              <span>Runs on: {runtimeTargets.length > 0 ? runtimeTargets.join(', ') : (option.requires_gpu ? 'CUDA' : 'CPU or CUDA')}</span>
                                              <span>Backend: {backend || 'catalog entry'}</span>
                                              <span>Rate: {getProcessingRateGuidance(option)}</span>
                                              {option.stage === 'detector' && detectorClasses.length > 0 && (
                                                <span>Classes: {formatDetectorClassSummary(detectorClasses)}</span>
                                              )}
                                            </span>
                                          )}
                                        </span>
                                      </label>
                                    );
                                  })}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>

                      <div className="control-actions">
                        <button
                          type="button"
                          onClick={saveMountedModels}
                          className="secondary-button"
                          disabled={isSavingMountedModels}
                        >
                          {isSavingMountedModels ? mountedModelProgressLabel : mountedModelActionLabel}
                        </button>
                      </div>
                    </div>
                  )}

                  {modelLibrarySubTab === 'library' && (
                    <div className="card">
                    <div className="card-header">
                      <div>
                        <h3>Model Library</h3>
                        <p>Browse the AI models that Hearthlight can run, what each one does, and where it fits in the pipeline.</p>
                        <p className="muted-text">{modelZooSummary}</p>
                      </div>
                    </div>

                    <div className="model-library-stage-list">
                      {stageLibraryEntries.map((stage) => (
                        <div key={stage.stage} className="model-library-stage">
                          <div className="source-row-header">
                            <div>
                              <strong>{stage.title || stage.label}</strong>
                              <div className="muted-text">{stage.description}</div>
                            </div>
                            <div className="model-library-stage-meta">
                              <span>{stage.options.length} available</span>
                              <span>{stage.mountedCount} mounted</span>
                              <span>Default: {stage.defaultDisplayName}</span>
                            </div>
                          </div>

                          {stage.options.length === 0 ? (
                            <div className="empty-state">No {stage.label.toLowerCase()} models are currently registered.</div>
                          ) : (
                            <div className="model-library-grid">
                              {stage.options.map((option) => {
                                const detectorClasses = getModelClasses(option);
                                const runtimeTargets = getRuntimeTargets(option);
                                const sourceKinds = formatListLabel((option.capabilities?.source_kinds || []).map(normalizeSourceKindLabel));
                                const backend = option.runtime?.backend || option.runtime?.tracker_name || option.runtime?.person_strategy || option.runtime?.package || null;
                                return (
                                  <div key={option.model_key} className="model-library-card">
                                    <div className="source-row-header">
                                      <div>
                                        <strong>{option.display_name || option.model_key}</strong>
                                        <div className="muted-text">{describeModelOption(option)}</div>
                                      </div>
                                      <div className="model-library-badges">
                                        {defaultBindings[stage.stage] === option.model_key && <span className="model-library-badge">Default</span>}
                                        {option.is_mounted && <span className="model-library-badge">Mounted</span>}
                                        {option.requires_gpu && <span className="model-library-badge">GPU required</span>}
                                        {option.option_origin === 'local_override' && <span className="model-library-badge">Override</span>}
                                      </div>
                                    </div>

                                    <div className="empty-state model-library-summary">
                                      <strong>Used for</strong>
                                      <div className="muted-text">{stage.usedFor}</div>
                                      <div className="muted-text">{describeModelFit(option)}</div>
                                      {option.stage === 'detector' && hasExpandedDetectorClasses(detectorClasses) && (
                                        <div className="muted-text">
                                          Available detector classes include {formatDetectorClassSummary(detectorClasses)}.
                                        </div>
                                      )}
                                    </div>

                                    <div className="model-library-fact-grid">
                                      <div className="model-library-fact">
                                        <span className="model-library-fact-label">Model ID</span>
                                        <code>{formatLibraryModelId(option.model_key)}</code>
                                      </div>
                                      <div className="model-library-fact">
                                        <span className="model-library-fact-label">Adapter</span>
                                        <span>{option.adapter || 'n/a'}</span>
                                      </div>
                                      <div className="model-library-fact">
                                        <span className="model-library-fact-label">Runs On</span>
                                        <span>{runtimeTargets.length > 0 ? runtimeTargets.join(', ') : (option.requires_gpu ? 'CUDA' : 'CPU or CUDA')}</span>
                                      </div>
                                      <div className="model-library-fact">
                                        <span className="model-library-fact-label">Backend</span>
                                        <span>{backend || 'catalog entry'}</span>
                                      </div>
                                      <div className="model-library-fact">
                                        <span className="model-library-fact-label">Processing Rate</span>
                                        <span>{getProcessingRateGuidance(option)}</span>
                                      </div>
                                      {option.stage === 'detector' && detectorClasses.length > 0 && (
                                        <div className="model-library-fact">
                                          <span className="model-library-fact-label">Available Classes</span>
                                          <span>{formatDetectorClassSummary(detectorClasses)}</span>
                                        </div>
                                      )}
                                      <div className="model-library-fact">
                                        <span className="model-library-fact-label">Source Types</span>
                                        <span>{sourceKinds || 'n/a'}</span>
                                      </div>
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                    </div>
                  )}
                </div>

                <div className="control-column">
                  <div className="card">
                    <div className="card-header">
                      <div>
                        <h3>How to Use This Page</h3>
                        <p>Use this library to understand which model you want before you set a default binding or a source-specific override.</p>
                      </div>
                    </div>
                    <div className="empty-state endpoint-info">
                      <strong>How model choice works</strong>
                      <div className="muted-text">1. Pick a default model per stage in the Sources tab.</div>
                      <div className="muted-text">2. Override a model on an individual source only when that source needs something different.</div>
                      <div className="muted-text">3. Alert rules then use the effective detector model and the saved anomaly prompt lists for their available targets.</div>
                      <div className="muted-text">Processing Rate is qualitative guidance only. Live cadence depends on camera FPS and frame skipping.</div>
                    </div>
                  </div>

                  <div className="card">
                    <div className="card-header">
                      <div>
                        <h3>Catalog API</h3>
                        <p>The library is prepared from the backend model catalog rather than from frontend parsing.</p>
                      </div>
                    </div>
                    <div className="empty-state endpoint-info">
                      <strong>GET {`${BaseURL}/model-options`}</strong>
                      <div className="muted-text">Returns readable model names, stable model keys, stage groupings, and origin metadata.</div>
                      <div className="muted-text">Use this to drive model pickers, audits, or external operator tooling.</div>
                    </div>
                  </div>
                </div>
              </section>
            </>
          ))}

          {renderTabSection('rules', (
            <>
              {banner && (
                <div className={`banner banner-${banner.kind}`}>
                  {banner.text}
                </div>
              )}

              <section className="control-column">
                  <div className="card">
                    <div className="card-header">
                      <div>
                        <h3>Rules</h3>
                        <p>Define detection rules and anomaly detection rules, each with multi-camera targeting.</p>
                      </div>
                    </div>

                    <div className="source-list">
                      {alertRuleLoadHint && (
                        <div className="empty-state">{alertRuleLoadHint}</div>
                      )}

                      <div className="source-row">
                        <div className="source-row-header">
                          <div>
                            <strong>Detection Rules</strong>
                            <div className="muted-text">Use detector targets like `PERSON` and `BAG` with a confidence threshold from `0.0` to `1.0`.</div>
                          </div>
                          <button type="button" onClick={() => addAlertRule('detector')} className="secondary-button">
                            Add Detection Rule
                          </button>
                        </div>
                        {detectionRules.length === 0 ? (
                          <div className="empty-state">No detection rules configured yet.</div>
                        ) : (
                          <div className="source-list">
                            {detectionRules.map((rule, ruleIndex) => {
                              const selectedSourceId = rule.source_ids?.[0];
                              const selectedSignalOptions = selectedSourceId ? getSignalOptionsForSource(selectedSourceId, 'detector') : null;
                              const targetOptions = (selectedSignalOptions?.options || []).slice().sort((a, b) => (a.label || '').localeCompare(b.label || ''));
                              const selectedTargetOption = targetOptions.find((option) => option.key === rule.target_key);
                              return (
                                <div key={rule.clientKey} className="source-row">
                                  <div className="source-row-header">
                                    <strong>Detection Rule {ruleIndex + 1}</strong>
                                    <div className="button-row">
                                      {!rule.isEditing && (
                                        <button type="button" onClick={() => editAlertRule(rule.clientKey)} className="secondary-button">Edit</button>
                                      )}
                                      <button type="button" onClick={() => removeAlertRule(rule.clientKey)} className="ghost-button">Remove</button>
                                    </div>
                                  </div>
                                  {rule.isEditing ? (
                                    <div className="model-binding-grid">
                                      <label>
                                        <span>Rule Label</span>
                                        <input type="text" value={rule.rule_label} onChange={(event) => setAlertRuleField(rule.clientKey, 'rule_label', event.target.value)} placeholder="Optional operator label" />
                                      </label>
                                      <div className="camera-rule-selector">
                                        <span>Applies To</span>
                                        <div className="camera-checkbox-grid">
                                          {sources.filter((source) => source.id).map((source, index) => (
                                            <label key={`${rule.clientKey}-detector-source-${source.id}`} className="model-mount-toggle">
                                              <input
                                                type="checkbox"
                                                checked={(rule.source_ids || []).includes(source.id)}
                                                onChange={(event) => toggleAlertRuleSource(rule.clientKey, source.id, event.target.checked)}
                                              />
                                              <span>{source.label?.trim() || defaultSourceLabel(source, index, sources)}</span>
                                            </label>
                                          ))}
                                        </div>
                                      </div>
                                      <label>
                                        <span>Detector Target</span>
                                        <select value={rule.target_key} onChange={(event) => setAlertRuleField(rule.clientKey, 'target_key', event.target.value)}>
                                          <option value="">Select target</option>
                                          {targetOptions.map((option) => (
                                            <option key={option.key} value={option.key}>{option.label}</option>
                                          ))}
                                        </select>
                                        {selectedTargetOption?.description && <small className="muted-text">{selectedTargetOption.description}</small>}
                                      </label>
                                      <label>
                                        <span>Confidence Threshold</span>
                                        <input type="number" min="0" max="1" step="0.01" value={rule.min_confidence} onChange={(event) => setAlertRuleField(rule.clientKey, 'min_confidence', event.target.value)} />
                                      </label>
                                      <label>
                                        <span>Alert Level</span>
                                        <select value={rule.alert_level} onChange={(event) => setAlertRuleField(rule.clientKey, 'alert_level', event.target.value)}>
                                          {ALERT_LEVEL_OPTIONS.map((option) => (
                                            <option key={option.value} value={option.value}>{option.label}</option>
                                          ))}
                                        </select>
                                      </label>
                                      <label className="toggle-field">
                                        <span>Enabled</span>
                                        <input type="checkbox" checked={rule.enabled} onChange={(event) => setAlertRuleField(rule.clientKey, 'enabled', event.target.checked)} />
                                      </label>
                                      <div className="camera-rule-selector full-width-field">
                                        <span>Connectors To Activate</span>
                                        {alertRuleConnectorTargets.length === 0 ? (
                                          <div className="empty-state">No enabled saved connectors are available yet.</div>
                                        ) : (
                                          <div className="camera-checkbox-grid">
                                            {alertRuleConnectorTargets.map((connector) => (
                                              <label key={`${rule.clientKey}-connector-${connector.id}`} className="model-mount-toggle">
                                                <input
                                                  type="checkbox"
                                                  checked={(rule.delivery_target_ids || []).includes(connector.id)}
                                                  onChange={(event) => toggleAlertRuleConnectorTarget(rule.clientKey, connector.id, event.target.checked)}
                                                />
                                                <span>
                                                  {connector.label}
                                                  {connector.description ? ` · ${connector.description}` : ''}
                                                </span>
                                              </label>
                                            ))}
                                          </div>
                                        )}
                                      </div>
                                      <div className="control-actions">
                                        <button type="button" onClick={() => cancelAlertRuleEdit(rule.clientKey)} className="ghost-button">Cancel</button>
                                      </div>
                                    </div>
                                  ) : (
                                    <div className="rule-summary-grid">
                                      <div><span className="settings-modal-label">Rule</span><strong>{rule.rule_label?.trim() || `Detection Rule ${ruleIndex + 1}`}</strong></div>
                                      <div><span className="settings-modal-label">Target</span><strong>{selectedTargetOption?.label || rule.target_key || 'Not set'}</strong></div>
                                      <div><span className="settings-modal-label">Applies To</span><strong>{(rule.source_ids || []).map((sourceId) => getSourceDisplayName(sourceId)).join(', ') || 'No sources selected'}</strong></div>
                                      <div><span className="settings-modal-label">Confidence</span><strong>{Number(rule.min_confidence).toFixed(2)}</strong></div>
                                      <div><span className="settings-modal-label">Alert Level</span><strong>{rule.alert_level}</strong></div>
                                      <div><span className="settings-modal-label">Enabled</span><strong>{rule.enabled ? 'Yes' : 'No'}</strong></div>
                                      <div className="full-width-field"><span className="settings-modal-label">Connectors</span><strong>{formatAlertRuleConnectorSummary(rule.delivery_target_ids)}</strong></div>
                                    </div>
                                  )}
                                  {alertRuleErrors[rule.clientKey] && <div className="row-error">{alertRuleErrors[rule.clientKey]}</div>}
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>

                      <div className="source-row">
                        <div className="source-row-header">
                          <div>
                            <strong>Anomaly Detection Rules</strong>
                            <div className="muted-text">Use saved anomaly objects or behaviors with a `1-10` trigger cutoff per rule.</div>
                          </div>
                          <button type="button" onClick={() => addAlertRule('anomaly')} className="secondary-button">
                            Add Anomaly Rule
                          </button>
                        </div>
                        {anomalyRules.length === 0 ? (
                          <div className="empty-state">No anomaly detection rules configured yet.</div>
                        ) : (
                          <div className="source-list">
                            {anomalyRules.map((rule, ruleIndex) => {
                              const signalFamily = rule.anomaly_target_kind === 'behavior' ? 'anomaly_activity' : 'anomaly_object';
                              const selectedSourceId = rule.source_ids?.[0];
                              const selectedSignalOptions = selectedSourceId ? getSignalOptionsForSource(selectedSourceId, signalFamily) : null;
                              const targetOptions = (selectedSignalOptions?.options || []).slice().sort((a, b) => (a.label || '').localeCompare(b.label || ''));
                              return (
                                <div key={rule.clientKey} className="source-row">
                                  <div className="source-row-header">
                                    <strong>Anomaly Rule {ruleIndex + 1}</strong>
                                    <div className="button-row">
                                      {!rule.isEditing && (
                                        <button type="button" onClick={() => editAlertRule(rule.clientKey)} className="secondary-button">Edit</button>
                                      )}
                                      <button type="button" onClick={() => removeAlertRule(rule.clientKey)} className="ghost-button">Remove</button>
                                    </div>
                                  </div>
                                  {rule.isEditing ? (
                                    <div className="model-binding-grid">
                                      <label>
                                        <span>Rule Label</span>
                                        <input type="text" value={rule.rule_label} onChange={(event) => setAlertRuleField(rule.clientKey, 'rule_label', event.target.value)} placeholder="Optional operator label" />
                                      </label>
                                      <div className="camera-rule-selector">
                                        <span>Applies To</span>
                                        <div className="camera-checkbox-grid">
                                          {sources.filter((source) => source.id).map((source, index) => (
                                            <label key={`${rule.clientKey}-anomaly-source-${source.id}`} className="model-mount-toggle">
                                              <input
                                                type="checkbox"
                                                checked={(rule.source_ids || []).includes(source.id)}
                                                onChange={(event) => toggleAlertRuleSource(rule.clientKey, source.id, event.target.checked)}
                                              />
                                              <span>{source.label?.trim() || defaultSourceLabel(source, index, sources)}</span>
                                            </label>
                                          ))}
                                        </div>
                                      </div>
                                      <label>
                                        <span>Anomaly Type</span>
                                        <select
                                          value={rule.anomaly_target_kind || 'object'}
                                          onChange={(event) => {
                                            const nextKind = event.target.value;
                                            setAlertRuleField(rule.clientKey, 'anomaly_target_kind', nextKind);
                                            setAlertRuleSignalFamily(rule.clientKey, nextKind === 'behavior' ? 'anomaly_activity' : 'anomaly_object');
                                          }}
                                        >
                                          {ANOMALY_TARGET_KIND_OPTIONS.map((option) => (
                                            <option key={option.value} value={option.value}>{option.label}</option>
                                          ))}
                                        </select>
                                      </label>
                                      <label>
                                        <span>Target</span>
                                        <select value={rule.target_key} onChange={(event) => setAlertRuleField(rule.clientKey, 'target_key', event.target.value)}>
                                          <option value="">Select target</option>
                                          {targetOptions.map((option) => (
                                            <option key={option.key} value={option.key}>{option.label}</option>
                                          ))}
                                        </select>
                                      </label>
                                      <label>
                                        <span>Trigger Cutoff (1-10)</span>
                                        <input type="number" min="1" max="10" step="1" value={rule.anomaly_cutoff ?? 6} onChange={(event) => setAlertRuleField(rule.clientKey, 'anomaly_cutoff', event.target.value)} />
                                      </label>
                                      <label>
                                        <span>Alert Level</span>
                                        <select value={rule.alert_level} onChange={(event) => setAlertRuleField(rule.clientKey, 'alert_level', event.target.value)}>
                                          {ALERT_LEVEL_OPTIONS.map((option) => (
                                            <option key={option.value} value={option.value}>{option.label}</option>
                                          ))}
                                        </select>
                                      </label>
                                      <label className="toggle-field">
                                        <span>Enabled</span>
                                        <input type="checkbox" checked={rule.enabled} onChange={(event) => setAlertRuleField(rule.clientKey, 'enabled', event.target.checked)} />
                                      </label>
                                      <div className="camera-rule-selector full-width-field">
                                        <span>Connectors To Activate</span>
                                        {alertRuleConnectorTargets.length === 0 ? (
                                          <div className="empty-state">No enabled saved connectors are available yet.</div>
                                        ) : (
                                          <div className="camera-checkbox-grid">
                                            {alertRuleConnectorTargets.map((connector) => (
                                              <label key={`${rule.clientKey}-connector-${connector.id}`} className="model-mount-toggle">
                                                <input
                                                  type="checkbox"
                                                  checked={(rule.delivery_target_ids || []).includes(connector.id)}
                                                  onChange={(event) => toggleAlertRuleConnectorTarget(rule.clientKey, connector.id, event.target.checked)}
                                                />
                                                <span>
                                                  {connector.label}
                                                  {connector.description ? ` · ${connector.description}` : ''}
                                                </span>
                                              </label>
                                            ))}
                                          </div>
                                        )}
                                      </div>
                                      <div className="control-actions">
                                        <button type="button" onClick={() => cancelAlertRuleEdit(rule.clientKey)} className="ghost-button">Cancel</button>
                                      </div>
                                    </div>
                                  ) : (
                                    <div className="rule-summary-grid">
                                      <div><span className="settings-modal-label">Rule</span><strong>{rule.rule_label?.trim() || `Anomaly Rule ${ruleIndex + 1}`}</strong></div>
                                      <div><span className="settings-modal-label">Type</span><strong>{rule.anomaly_target_kind === 'behavior' ? 'Behavior' : 'Object'}</strong></div>
                                      <div><span className="settings-modal-label">Target</span><strong>{rule.target_key || 'Not set'}</strong></div>
                                      <div><span className="settings-modal-label">Applies To</span><strong>{(rule.source_ids || []).map((sourceId) => getSourceDisplayName(sourceId)).join(', ') || 'No sources selected'}</strong></div>
                                      <div><span className="settings-modal-label">Cutoff</span><strong>{rule.anomaly_cutoff ?? 6}</strong></div>
                                      <div><span className="settings-modal-label">Alert Level</span><strong>{rule.alert_level}</strong></div>
                                      <div><span className="settings-modal-label">Enabled</span><strong>{rule.enabled ? 'Yes' : 'No'}</strong></div>
                                      <div className="full-width-field"><span className="settings-modal-label">Connectors</span><strong>{formatAlertRuleConnectorSummary(rule.delivery_target_ids)}</strong></div>
                                    </div>
                                  )}
                                  {alertRuleErrors[rule.clientKey] && <div className="row-error">{alertRuleErrors[rule.clientKey]}</div>}
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="control-actions">
                      <button type="button" onClick={saveAlertRules} className="secondary-button" disabled={isSavingAlertRules}>
                        {isSavingAlertRules ? 'Saving...' : 'Save Rules'}
                      </button>
                    </div>
                  </div>
                </section>
            </>
          ))}

          {renderTabSection('connectors', (
            <>
              {banner && (
                <div className={`banner banner-${banner.kind}`}>
                  {banner.text}
                </div>
              )}

              <div className="settings-subtabs">
                {CONNECTOR_SUB_TABS.map((tab) => (
                  <button
                    key={tab.key}
                    type="button"
                    className={connectorSubTab === tab.key ? 'settings-subtab active' : 'settings-subtab'}
                    onClick={() => setConnectorSubTab(tab.key)}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

              {connectorSubTab === 'connections' && (
                <section className="control-grid connectors-grid">
                  {genericInstalledConnectorEndpoints.length > 0 && (
                    <div className="card">
                      <div className="card-header">
                        <div>
                          <div className="connector-header-line">
                            <h3>Installed Connector Plugins</h3>
                          </div>
                          <p>Connectors added from the Connector Zoo appear here after they are added to this workspace.</p>
                        </div>
                      </div>
                      <div className="source-list">
                        {genericInstalledConnectorEndpoints.map((endpoint, index) => (
                          <div key={`generic-connector-${endpoint.id || index}`} className="source-row">
                            <div className="source-row-header">
                              <div>
                                <strong>{endpoint.label || endpoint.connector_key}</strong>
                                <div className="muted-text">Connector key: {endpoint.connector_key}</div>
                              </div>
                              <span className={`connector-status-badge ${endpoint.resolved ? 'connector-status-badge-ok' : 'connector-status-badge-pending'}`}>
                                {endpoint.resolved ? 'Installed' : 'Restart required'}
                              </span>
                            </div>
                            {endpoint.unavailable_reason && (
                              <div className="row-error">{endpoint.unavailable_reason}</div>
                            )}
                            <div className="muted-text">
                              {endpoint.resolved
                                ? 'This connector is installed and managed through the generic connector endpoint registry.'
                                : 'This connector row was added, but the plugin runtime is not active yet. Restart Hearthlight to activate it.'}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {(goveeEndpoints.length > 0) && (
                    <div className="card">
                      <div className="card-header">
                        <div>
                          <div className="connector-header-line">
                            <h3>Govee Light Connection</h3>
                            <span className={`connector-status-badge ${isGoveeConnectorConfigured ? 'connector-status-badge-ok' : 'connector-status-badge-pending'}`}>
                              {isGoveeConnectorConfigured ? 'Configured' : 'Needs setup'}
                            </span>
                          </div>
                          <p>Use a Govee account to discover light-capable devices and trigger light actions when Hearthlight rules fire.</p>
                        </div>
                        <button type="button" onClick={addGoveeEndpoint} className="secondary-button">
                          Add Connection
                        </button>
                      </div>

                      <div className="source-list">
                        {goveeEndpoints.map((endpoint, index) => {
                          const devices = goveeDiscoveryResults[endpoint.clientKey] || [];
                          const selectedDevice = devices.find((device) => device.sku === endpoint.sku && device.device === endpoint.device);
                          const capabilityOptions = selectedDevice?.capability_options || [];
                          const selectedCapability = capabilityOptions.find((option) => option.key === endpoint.capability_key);
                          const enumValues = selectedCapability?.values || [];
                          const isColorInput = selectedCapability?.input_kind === 'color';
                          const colorValue = Number(endpoint.capability_value || 0);
                          const colorHex = `#${Math.max(0, colorValue).toString(16).padStart(6, '0').slice(-6)}`;
                          return (
                            <div key={endpoint.clientKey} className="source-row">
                              <div className="source-row-header">
                                <strong>Connection {index + 1}</strong>
                                <button type="button" onClick={() => removeGoveeEndpoint(endpoint.clientKey)} className="ghost-button">Remove</button>
                              </div>
                              <div className="model-binding-grid">
                                <label>
                                  <span>Label</span>
                                  <input
                                    type="text"
                                    value={endpoint.label}
                                    onChange={(event) => setGoveeEndpointField(endpoint.clientKey, 'label', event.target.value)}
                                    placeholder="Optional operator label"
                                  />
                                </label>
                                <label>
                                  <span>API Key</span>
                                  <input
                                    type="password"
                                    value={endpoint.api_key}
                                    onChange={(event) => setGoveeEndpointField(endpoint.clientKey, 'api_key', event.target.value)}
                                    placeholder="Govee API key"
                                  />
                                </label>
                                <label className="toggle-field">
                                  <span>Enabled</span>
                                  <input
                                    type="checkbox"
                                    checked={endpoint.enabled}
                                    onChange={(event) => setGoveeEndpointField(endpoint.clientKey, 'enabled', event.target.checked)}
                                  />
                                </label>
                                <label>
                                  <span>Device</span>
                                  <select
                                    value={endpoint.sku && endpoint.device ? `${endpoint.sku}:${endpoint.device}` : ''}
                                    onChange={(event) => applyGoveeDeviceSelection(endpoint.clientKey, event.target.value)}
                                  >
                                    <option value="">Select discovered light</option>
                                    {devices.map((device) => (
                                      <option key={`${device.sku}:${device.device}`} value={`${device.sku}:${device.device}`}>
                                        {device.device_name} ({device.sku})
                                      </option>
                                    ))}
                                  </select>
                                </label>
                                <label>
                                  <span>Action</span>
                                  <select
                                    value={endpoint.capability_key}
                                    onChange={(event) => applyGoveeCapabilitySelection(endpoint.clientKey, event.target.value)}
                                    disabled={!selectedDevice}
                                  >
                                    <option value="">Select action</option>
                                    {capabilityOptions.map((option) => (
                                      <option key={option.key} value={option.key}>{option.label}</option>
                                    ))}
                                  </select>
                                </label>
                                {selectedCapability?.input_kind === 'enum' && (
                                  <label>
                                    <span>Action Value</span>
                                    <select
                                      value={endpoint.capability_value}
                                      onChange={(event) => {
                                        const selectedValue = enumValues.find((item) => `${item.value}` === event.target.value);
                                        setGoveeEndpointField(endpoint.clientKey, 'capability_value', Number.isNaN(Number(event.target.value)) ? event.target.value : Number(event.target.value));
                                        setGoveeEndpointField(endpoint.clientKey, 'capability_value_label', selectedValue?.label || '');
                                      }}
                                    >
                                      <option value="">Select value</option>
                                      {enumValues.map((item) => (
                                        <option key={`${item.value}`} value={item.value}>{item.label}</option>
                                      ))}
                                    </select>
                                  </label>
                                )}
                                {selectedCapability?.input_kind === 'integer' && (
                                  <label>
                                    <span>Action Value</span>
                                    <input
                                      type="number"
                                      min={selectedCapability.range?.min ?? 0}
                                      max={selectedCapability.range?.max ?? 100}
                                      step={selectedCapability.range?.precision ?? 1}
                                      value={endpoint.capability_value}
                                      onChange={(event) => setGoveeEndpointField(endpoint.clientKey, 'capability_value', Number(event.target.value))}
                                    />
                                  </label>
                                )}
                                {isColorInput && (
                                  <label>
                                    <span>Color</span>
                                    <input
                                      type="color"
                                      value={colorHex}
                                      onChange={(event) => setGoveeEndpointField(endpoint.clientKey, 'capability_value', parseInt(event.target.value.replace('#', ''), 16))}
                                    />
                                  </label>
                                )}
                              </div>
                              <div className="control-actions">
                                <button
                                  type="button"
                                  onClick={() => testGoveeApiKey(endpoint)}
                                  className="ghost-button"
                                  disabled={Boolean(busyGoveeTests[endpoint.clientKey])}
                                >
                                  {busyGoveeTests[endpoint.clientKey] ? 'Testing...' : 'Test API Key'}
                                </button>
                                <button
                                  type="button"
                                  onClick={() => discoverGoveeDevices(endpoint)}
                                  className="ghost-button"
                                  disabled={Boolean(busyGoveeDiscovery[endpoint.clientKey])}
                                >
                                  {busyGoveeDiscovery[endpoint.clientKey] ? 'Discovering...' : 'Discover Devices'}
                                </button>
                                <button
                                  type="button"
                                  onClick={() => sendGoveeTestAction(endpoint)}
                                  className="ghost-button"
                                  disabled={Boolean(busyGoveeTests[endpoint.clientKey])}
                                >
                                  {busyGoveeTests[endpoint.clientKey] ? 'Sending Test...' : 'Send Test Action'}
                                </button>
                              </div>
                              {goveeDiscoveryMessages[endpoint.clientKey] && (
                                <div className="muted-text">{goveeDiscoveryMessages[endpoint.clientKey]}</div>
                              )}
                              {goveeEndpointErrors[endpoint.clientKey] && (
                                <div className="row-error">{goveeEndpointErrors[endpoint.clientKey]}</div>
                              )}
                            </div>
                          );
                        })}
                      </div>

                      <div className="control-actions">
                        <button
                          type="button"
                          onClick={saveGoveeEndpoints}
                          className="secondary-button"
                          disabled={isSavingGoveeEndpoints}
                        >
                          {isSavingGoveeEndpoints ? 'Saving...' : 'Save Govee Light Connections'}
                        </button>
                      </div>

                      <div className="empty-state endpoint-info">
                        <div className="muted-text">GET/PUT {`${BaseURL}/settings/govee-connector-endpoints`}</div>
                        <div className="muted-text">POST {`${BaseURL}/settings/govee/test`}</div>
                        <div className="muted-text">GET {`${BaseURL}/settings/govee/devices`}</div>
                        <div className="muted-text">POST {`${BaseURL}/settings/govee-connector-endpoints/test`}</div>
                      </div>
                    </div>
                  )}

                  <div className="card">
                    <div className="card-header">
                      <div>
                        <div className="connector-header-line">
                          <h3>Telegram</h3>
                          <span className={`connector-status-badge ${isTelegramConnectorConfigured ? 'connector-status-badge-ok' : 'connector-status-badge-pending'}`}>
                            {isTelegramConnectorConfigured ? 'Configured' : 'Needs setup'}
                          </span>
                        </div>
                        <p>Send each new trigger to one or more Telegram chats using a bot token and chat ID.</p>
                      </div>
                      <button
                        type="button"
                        onClick={addTelegramSubscription}
                        className="secondary-button"
                      >
                        Add Subscription
                      </button>
                    </div>

                    {telegramSubscriptions.length === 0 ? (
                      <div className="empty-state">
                        No Telegram trigger subscriptions saved yet.
                      </div>
                    ) : (
                      <div className="source-list">
                        {telegramSubscriptions.map((subscription, index) => (
                          <div key={subscription.clientKey} className="source-row">
                            <div className="source-row-header">
                              <strong>Subscription {index + 1}</strong>
                              <button
                                type="button"
                                onClick={() => removeTelegramSubscription(subscription.clientKey)}
                                className="ghost-button"
                              >
                                Remove
                              </button>
                            </div>

                            <div className="model-binding-grid">
                              <label>
                                <span>Label</span>
                                <input
                                  type="text"
                                  value={subscription.subscription_label}
                                  onChange={(event) => setTelegramSubscriptionField(subscription.clientKey, 'subscription_label', event.target.value)}
                                  placeholder="Optional operator label"
                                />
                              </label>
                              <label>
                                <span>Bot Token</span>
                                <input
                                  type="password"
                                  value={subscription.bot_token}
                                  onChange={(event) => setTelegramSubscriptionField(subscription.clientKey, 'bot_token', event.target.value)}
                                  placeholder="123456:ABC..."
                                />
                              </label>
                              <label>
                                <span>Chat ID</span>
                                <input
                                  type="text"
                                  value={subscription.chat_id}
                                  onChange={(event) => setTelegramSubscriptionField(subscription.clientKey, 'chat_id', event.target.value)}
                                  placeholder="e.g. -1001234567890 or @channel_name"
                                />
                              </label>
                              <label className="toggle-field">
                                <span>Enabled</span>
                                <input
                                  type="checkbox"
                                  checked={subscription.enabled}
                                  onChange={(event) => setTelegramSubscriptionField(subscription.clientKey, 'enabled', event.target.checked)}
                                />
                              </label>
                              <label className="toggle-field">
                                <span>Send Media</span>
                                <input
                                  type="checkbox"
                                  checked={Boolean(subscription.send_media)}
                                  onChange={(event) => setTelegramSubscriptionField(subscription.clientKey, 'send_media', event.target.checked)}
                                />
                              </label>
                              <label>
                                <span>Media Source</span>
                                <select
                                  value={subscription.media_source || 'none'}
                                  onChange={(event) => setTelegramSubscriptionField(subscription.clientKey, 'media_source', event.target.value)}
                                  disabled={!subscription.send_media}
                                >
                                  <option value="none">None (Text only)</option>
                                  <option value="frame_snapshot">Frame Snapshot (Telegram photo: thumbnail + tap to expand)</option>
                                </select>
                              </label>
                            </div>

                            <div className="control-actions">
                              <button
                                type="button"
                                onClick={() => sendTelegramTestMessage(subscription)}
                                className="ghost-button"
                                disabled={Boolean(busyTelegramTests[subscription.clientKey])}
                              >
                                {busyTelegramTests[subscription.clientKey] ? 'Sending Test...' : 'Send Test Message'}
                              </button>
                            </div>

                            {telegramSubscriptionErrors[subscription.clientKey] && (
                              <div className="row-error">{telegramSubscriptionErrors[subscription.clientKey]}</div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}

                    <div className="control-actions">
                      <button
                        type="button"
                        onClick={saveTelegramSubscriptions}
                        className="secondary-button"
                        disabled={isSavingTelegramSubscriptions}
                      >
                        {isSavingTelegramSubscriptions ? 'Saving...' : 'Save Telegram Subscriptions'}
                      </button>
                    </div>

                    <div className="empty-state endpoint-info">
                      <div className="muted-text">GET/PUT {`${BaseURL}/settings/telegram-trigger-subscriptions`}</div>
                      <div className="muted-text">POST {`${BaseURL}/settings/telegram-trigger-subscriptions/test`}</div>
                      <div className="muted-text">Each enabled subscriber receives a Telegram message whenever a new trigger row is created.</div>
                    </div>
                  </div>
                  <div className="card">
                    <div className="card-header">
                      <div>
                        <div className="connector-header-line">
                          <h3>Apple Messages</h3>
                          <span className={`connector-status-badge ${isAppleMessagesConnectorConfigured ? 'connector-status-badge-ok' : 'connector-status-badge-pending'}`}>
                            {isAppleMessagesConnectorConfigured ? 'Configured' : 'Needs setup'}
                          </span>
                        </div>
                        <p>Send each new trigger to one or more Apple Messages recipients from the macOS host running Hearthlight.</p>
                      </div>
                      <button
                        type="button"
                        onClick={addAppleMessageSubscription}
                        className="secondary-button"
                      >
                        Add Subscription
                      </button>
                    </div>

                    {appleMessageSubscriptions.length === 0 ? (
                      <div className="empty-state">
                        No Apple Messages trigger subscriptions saved yet.
                      </div>
                    ) : (
                      <div className="source-list">
                        {appleMessageSubscriptions.map((subscription, index) => (
                          <div key={subscription.clientKey} className="source-row">
                            <div className="source-row-header">
                              <strong>Subscription {index + 1}</strong>
                              <button
                                type="button"
                                onClick={() => removeAppleMessageSubscription(subscription.clientKey)}
                                className="ghost-button"
                              >
                                Remove
                              </button>
                            </div>

                            <div className="model-binding-grid">
                              <label>
                                <span>Label</span>
                                <input
                                  type="text"
                                  value={subscription.subscription_label}
                                  onChange={(event) => setAppleMessageSubscriptionField(subscription.clientKey, 'subscription_label', event.target.value)}
                                  placeholder="Optional operator label"
                                />
                              </label>
                              <label>
                                <span>Recipient Handle</span>
                                <input
                                  type="text"
                                  value={subscription.recipient_handle}
                                  onChange={(event) => setAppleMessageSubscriptionField(subscription.clientKey, 'recipient_handle', event.target.value)}
                                  placeholder="Phone number or Apple ID email"
                                />
                              </label>
                              <label>
                                <span>Service</span>
                                <select
                                  value={subscription.service}
                                  onChange={(event) => setAppleMessageSubscriptionField(subscription.clientKey, 'service', event.target.value)}
                                >
                                  <option value="iMessage">iMessage</option>
                                  <option value="SMS">SMS</option>
                                </select>
                              </label>
                              <label className="toggle-field">
                                <span>Enabled</span>
                                <input
                                  type="checkbox"
                                  checked={subscription.enabled}
                                  onChange={(event) => setAppleMessageSubscriptionField(subscription.clientKey, 'enabled', event.target.checked)}
                                />
                              </label>
                            </div>

                            <div className="control-actions">
                              <button
                                type="button"
                                onClick={() => sendAppleMessageTest(subscription)}
                                className="ghost-button"
                                disabled={Boolean(busyAppleMessageTests[subscription.clientKey])}
                              >
                                {busyAppleMessageTests[subscription.clientKey] ? 'Sending Test...' : 'Send Test Message'}
                              </button>
                            </div>

                            {appleMessageSubscriptionErrors[subscription.clientKey] && (
                              <div className="row-error">{appleMessageSubscriptionErrors[subscription.clientKey]}</div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}

                    <div className="control-actions">
                      <button
                        type="button"
                        onClick={saveAppleMessageSubscriptions}
                        className="secondary-button"
                        disabled={isSavingAppleMessageSubscriptions}
                      >
                        {isSavingAppleMessageSubscriptions ? 'Saving...' : 'Save Apple Messages Subscriptions'}
                      </button>
                    </div>

                    <div className="empty-state endpoint-info">
                      <div className="muted-text">GET/PUT {`${BaseURL}/settings/apple-message-trigger-subscriptions`}</div>
                      <div className="muted-text">POST {`${BaseURL}/settings/apple-message-trigger-subscriptions/test`}</div>
                      <div className="muted-text">Apple Messages delivery requires the macOS host to be signed into Messages and allowed to automate it.</div>
                    </div>

                    <div className="empty-state endpoint-info">
                      <strong>Connector Notes</strong>
                      <div className="muted-text">Use Connectors to fan out trigger notifications without changing the core anomaly rules.</div>
                      <div className="muted-text">Telegram is network-delivered through a bot token and chat ID.</div>
                      <div className="muted-text">Apple Messages is host-local and depends on the macOS Messages app.</div>
                    </div>
                  </div>
                </section>
              )}

              {connectorSubTab === 'connector-zoo' && (
                <section className="control-grid connectors-grid">
                  <div className="card">
                    <div className="card-header">
                      <div>
                        <div className="connector-header-line">
                          <h3>Connector Zoo</h3>
                        </div>
                        <p>Optional connector plugins can be added here without being part of the default built-in connector set.</p>
                      </div>
                      <button
                        type="button"
                        onClick={() => reloadRepoConnectorZooCatalog().catch((error) => setBanner({
                          kind: 'error',
                          text: formatApiError(error, 'Failed to refresh Connector Zoo.'),
                        }))}
                        className="secondary-button"
                      >
                        Refresh Zoo
                      </button>
                    </div>

                    <div className="model-binding-grid">
                      <label>
                        <span>Catalog URL</span>
                        <input
                          type="url"
                          value={connectorZooRepoSettings.catalog_url}
                          onChange={(event) => setConnectorZooRepoSettings({ catalog_url: event.target.value })}
                          placeholder="https://raw.githubusercontent.com/.../connector_zoo.yaml"
                        />
                      </label>
                    </div>

                    <div className="control-actions">
                      <button
                        type="button"
                        onClick={saveConnectorZooRepoSettings}
                        className="secondary-button"
                        disabled={isSavingConnectorZooRepoSettings}
                      >
                        {isSavingConnectorZooRepoSettings ? 'Saving...' : 'Save Connector Zoo URL'}
                      </button>
                    </div>

                    <div className="empty-state endpoint-info">
                      <div className="muted-text">Source URL: {repoConnectorZooCatalog.source_url || connectorZooRepoSettings.catalog_url || 'Not configured yet'}</div>
                      <div className="muted-text">Last refreshed: {repoConnectorZooCatalog.last_refreshed_at || 'Not fetched yet'}</div>
                      {repoConnectorZooCatalog.generated_at && (
                        <div className="muted-text">Catalog generated: {repoConnectorZooCatalog.generated_at}</div>
                      )}
                      {repoConnectorZooCatalog.from_cache && (
                        <div className="muted-text">Showing cached results because the live repo fetch failed.</div>
                      )}
                      {repoConnectorZooCatalog.error && (
                        <div className="row-error">{repoConnectorZooCatalog.error}</div>
                      )}
                    </div>
                  </div>

                  <div className="card">
                    <div className="card-header">
                      <div>
                        <div className="connector-header-line">
                          <h3>Available Connectors</h3>
                        </div>
                        <p>Each entry comes from the remote repo catalog and can be added into this workspace.</p>
                      </div>
                    </div>

                    {repoConnectorEntries.length === 0 ? (
                      <div className="empty-state">No repo-backed connector entries are available yet. Save a catalog URL and refresh the zoo.</div>
                    ) : (
                      <div className="source-list">
                        {repoConnectorEntries.map((entry) => (
                          <div key={`repo-connector-${entry.key}`} className="source-row">
                            <div className="source-row-header">
                              <div>
                                <strong>{entry.label}</strong>
                                <div className="muted-text">{entry.description}</div>
                              </div>
                              <button
                                type="button"
                                onClick={() => installRepoConnector(entry.key)}
                                className="secondary-button"
                                disabled={installingRepoConnectorKey === entry.key}
                              >
                                {installingRepoConnectorKey === entry.key
                                  ? 'Adding...'
                                  : (entry.installed ? 'Add Connection' : 'Add to System')}
                              </button>
                            </div>
                            <div className="muted-text">Plugin: {entry.plugin_key}{entry.plugin_version ? ` · ${entry.plugin_version}` : ''}</div>
                            {entry.source_url && (
                              <div className="muted-text">
                                <a href={entry.source_url} target="_blank" rel="noreferrer">Open source listing</a>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </section>
              )}
            </>
          ))}

          {renderTabSection('appearance', (
            <section className="control-grid">
              <div className="control-column">
                <div className="card">
                  <div className="card-header">
                    <div>
                      <h3>Workspace Theme</h3>
                      <p>Choose the shared Hearthlight theme for this workspace. The selected theme is persisted in backend settings and restored after app or server restarts.</p>
                    </div>
                  </div>

                  {appearanceMessage && (
                    <div className={`banner banner-${appearanceMessage.kind}`}>
                      {appearanceMessage.text}
                    </div>
                  )}

                  {appearanceError && (
                    <div className="row-error">
                      {appearanceError}
                    </div>
                  )}

                  {!appearanceLoaded && (
                    <div className="empty-state">Loading workspace appearance settings...</div>
                  )}

                  <div className="appearance-theme-groups">
                    {themeGroupsInOrder.map((groupKey) => (
                      <div key={groupKey} className="appearance-theme-group">
                        <div className="source-row-header">
                          <strong>{THEME_GROUP_LABELS[groupKey] || groupKey}</strong>
                        </div>
                        <div className="appearance-theme-grid">
                          {groupedThemeOptions[groupKey].map((option) => (
                            <button
                              key={option.key}
                              type="button"
                              className={`appearance-theme-card ${draftThemeKey === option.key ? 'appearance-theme-card-active' : ''}`}
                              onClick={() => {
                                setAppearanceMessage(null);
                                setDraftThemeKey(option.key);
                              }}
                            >
                              <div className="appearance-theme-card-header">
                                <strong>{option.label}</strong>
                                <span className="appearance-theme-card-state">
                                  {draftThemeKey === option.key ? 'Selected' : 'Available'}
                                </span>
                              </div>
                              <div className="appearance-theme-swatches" aria-hidden="true">
                                {(option.swatches || []).map((swatch) => (
                                  <span
                                    key={`${option.key}-${swatch}`}
                                    className="appearance-theme-swatch"
                                    style={{ backgroundColor: swatch }}
                                  />
                                ))}
                              </div>
                              <p>{option.description}</p>
                            </button>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="control-actions">
                    <button
                      type="button"
                      onClick={saveAppearanceSettings}
                      className="secondary-button"
                      disabled={isSavingAppearance || !appearanceLoaded}
                    >
                      {isSavingAppearance ? (
                        <>
                          <span className="button-spinner" aria-hidden="true" />
                          Saving Appearance...
                        </>
                      ) : 'Save Appearance'}
                    </button>
                  </div>
                </div>
              </div>

              <div className="control-column">
                <div className="card">
                  <div className="card-header">
                    <div>
                      <h3>Theme Behavior</h3>
                      <p>Theme changes are shared across the workspace and applied consistently across the operator shell.</p>
                    </div>
                  </div>
                  <div className="empty-state endpoint-info">
                    <strong>GET/PUT {`${BaseURL}/settings/appearance`}</strong>
                    <div className="muted-text">The backend stores the workspace theme as the source of truth.</div>
                    <div className="muted-text">The browser keeps a local startup cache only to reduce theme flicker before the settings API responds.</div>
                    <div className="muted-text">Accessible mode is intended for higher-contrast operation and clearer focus visibility.</div>
                  </div>
                </div>
              </div>
            </section>
          ))}

          {renderTabSection('monitoring', (
            <MonitoringPage pollingEnabled={activeTab === 'monitoring'} />
          ))}

          {renderTabSection('initialization', (
            <div className="control-column">
              <div className="card">
                <div className="card-header">
                  <div>
                    <h3>Repository Initialization</h3>
                    <p>Prepare the command-line launch plan for the full Hearthlight system on this host.</p>
                  </div>
                </div>
                <div className="model-binding-grid">
                  <label>
                    <span>Execution Profile</span>
                    <select
                      value={launchPlan.profile}
                      onChange={(event) => setLaunchPlan((previous) => ({ ...previous, profile: event.target.value }))}
                    >
                      <option value="cpu">cpu</option>
                      <option value="cuda">cuda</option>
                    </select>
                  </label>
                  <label>
                    <span>Base Template</span>
                    <select
                      value={launchPlan.template}
                      onChange={(event) => setLaunchPlan((previous) => ({ ...previous, template: event.target.value }))}
                    >
                      {TEMPLATE_OPTIONS.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Source Preset</span>
                    <select
                      value={launchPlan.sourcePreset}
                      onChange={(event) => setLaunchPlan((previous) => ({ ...previous, sourcePreset: event.target.value }))}
                    >
                      <option value="template default">template default</option>
                      {TEMPLATE_OPTIONS.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  </label>
                  {launchPlan.profile === 'cuda' && (
                    <label>
                      <span>CUDA Visible Devices</span>
                      <input
                        type="text"
                        value={launchPlan.cudaVisibleDevices}
                        onChange={(event) => setLaunchPlan((previous) => ({ ...previous, cudaVisibleDevices: event.target.value }))}
                        placeholder="0"
                      />
                    </label>
                  )}
                  <label className="toggle-field">
                    <span>Open Dashboard</span>
                    <input
                      type="checkbox"
                      checked={launchPlan.openDashboard}
                      onChange={(event) => setLaunchPlan((previous) => ({ ...previous, openDashboard: event.target.checked }))}
                    />
                  </label>
                </div>
                <div className="empty-state command-preview">
                  <strong>Recommended Launch Command</strong>
                  <pre>{buildLaunchCommand(launchPlan)}</pre>
                </div>
                <div className="empty-state">
                  <strong>Startup Sequence</strong>
                  <div className="muted-text">1. Fill `.env` and `shared/configs/config.yaml` if they do not exist.</div>
                  <div className="muted-text">2. Run `python3 scripts/container_preflight.py`.</div>
                  <div className="muted-text">3. Run the generated launcher command from the repository root.</div>
                  <div className="muted-text">4. Save sources here — an enabled source starts the run automatically. Use Monitor Run only if you need to stop or restart manually.</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default SettingsPage;
