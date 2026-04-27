import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { BaseURL } from '../config';
import RunSection from './RunSection';
import MonitoringSection from './MonitoringSection';
import {
  formatUploadedVideoSummary,
  SUPPORTED_VIDEO_LABEL,
  validateSelectedVideoFile,
  VIDEO_UPLOAD_ACCEPT,
} from '../utils/videoUpload';
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
  { stage: 'reid', label: 'Person ReID', field: 'reid_model_key' },
  { stage: 'anomaly_stage_1', label: 'Anomaly Stage 1', field: 'anomaly_stage_1_model_key' },
  { stage: 'anomaly_stage_2', label: 'Anomaly Stage 2', field: 'anomaly_stage_2_model_key' },
];
const TEMPLATE_OPTIONS = ['active', 'example', 'master_config', 'office_config'];
const ALERT_SIGNAL_FAMILY_OPTIONS = [
  { value: 'detector', label: 'Detector' },
  { value: 'anomaly_object', label: 'Anomaly Object' },
  { value: 'anomaly_activity', label: 'Anomaly Activity' },
];
const ALERT_LEVEL_OPTIONS = [
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
];
const EMPTY_PROMPT_SETTINGS = {
  text_prompt_yaml: '',
  anomaly_type_yaml: '',
};
const SETTINGS_TABS = [
  { key: 'sources', label: 'Sources' },
  { key: 'model-library', label: 'Model Library' },
  { key: 'alerts', label: 'Alerts' },
  { key: 'run', label: 'Run' },
  { key: 'monitoring', label: 'Monitoring' },
  { key: 'initialization', label: 'Initialization' },
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
  reid: {
    title: 'Person ReID Models',
    description: 'These models help the system understand when the same person or bag has appeared before.',
    usedFor: 'Maintaining identity across time and camera views.',
  },
  anomaly_stage_1: {
    title: 'Anomaly Stage 1 Models',
    description: 'These models run an early pass that watches for simple presence and timing patterns before deeper anomaly reasoning.',
    usedFor: 'Lightweight anomaly screening and event prefiltering.',
  },
  anomaly_stage_2: {
    title: 'Anomaly Stage 2 Models',
    description: 'These models interpret Stage 1 events using saved prompts and anomaly lists, or pass events through unchanged.',
    usedFor: 'Prompt-based anomaly labeling and final anomaly interpretation.',
  },
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
  detector_model_key: null,
  tracker_model_key: null,
  reid_model_key: null,
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
  detector_model_key: source.detector_model_key ?? null,
  tracker_model_key: source.tracker_model_key ?? null,
  reid_model_key: source.reid_model_key ?? null,
  anomaly_stage_1_model_key: source.anomaly_stage_1_model_key ?? null,
  anomaly_stage_2_model_key: source.anomaly_stage_2_model_key ?? null,
});

const createAlertRuleDraft = (sourceId, signalFamily = 'detector') => ({
  clientKey: `settings-alert-rule-${Date.now()}-${Math.random().toString(16).slice(2)}`,
  id: null,
  source_id: sourceId,
  enabled: true,
  rule_label: '',
  signal_family: signalFamily,
  target_key: '',
  min_confidence: 0.5,
  alert_level: 'medium',
});

const hydrateAlertRule = (rule, fallbackIndex = 0) => ({
  clientKey: rule.id ? `settings-alert-rule-${rule.id}` : `settings-alert-rule-${fallbackIndex}-${Math.random().toString(16).slice(2)}`,
  id: rule.id ?? null,
  source_id: rule.source_id,
  enabled: rule.enabled ?? true,
  rule_label: rule.rule_label ?? '',
  signal_family: rule.signal_family ?? 'detector',
  target_key: rule.target_key ?? '',
  min_confidence: Number.isFinite(rule.min_confidence) ? rule.min_confidence : 0.5,
  alert_level: rule.alert_level ?? 'medium',
});

const sanitizeSourcesForApi = (sources) =>
  sources.map((source, index) => ({
    id: source.id ?? undefined,
    kind: source.kind,
    label: source.label.trim() || `Source ${index + 1}`,
    tasks: [...TASK_OPTIONS],
    enabled: source.enabled,
    order: index,
    source_value: source.kind === 'video_upload' ? null : source.source_value,
    upload_id: source.kind === 'video_upload' ? source.upload_id : null,
    detector_model_key: source.detector_model_key || null,
    tracker_model_key: source.tracker_model_key || null,
    reid_model_key: source.reid_model_key || null,
    anomaly_stage_1_model_key: source.anomaly_stage_1_model_key || null,
    anomaly_stage_2_model_key: source.anomaly_stage_2_model_key || null,
  }));

const sanitizeAlertRulesForApi = (rules) =>
  rules.map((rule) => ({
    id: rule.id ?? undefined,
    source_id: rule.source_id,
    enabled: rule.enabled,
    rule_label: rule.rule_label?.trim() || null,
    signal_family: rule.signal_family,
    target_key: rule.target_key,
    min_confidence: Number(rule.min_confidence),
    alert_level: rule.alert_level,
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

const DEFAULT_SOURCE_ENABLE_LABEL = 'Enable Video AI';

const sourcePlaceholder = (kind) => {
  if (kind === 'webcam') {
    return 'Device index, e.g. 0';
  }
  return 'rtsp://, http://, or stream URL';
};

const createLaunchPlan = () => ({
  mode: 'api',
  profile: 'cpu',
  template: 'active',
  sourcePreset: 'template default',
  cudaVisibleDevices: '0',
  openDashboard: true,
});

const buildLaunchCommand = (plan) => {
  const command = ['python3', 'run/run.py', 'start', '--mode', plan.mode, '--template', plan.template, '--profile', plan.profile];
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
    case 'reid':
      return `${name} is used to recognize when the same person or bag appears again later in the run.`;
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
  if (option.stage === 'reid') {
    return 'Best when you want person identity continuity plus the current hybrid bag flow.';
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

const SettingsPage = () => {
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
  const [isSavingAnomalyPrompts, setIsSavingAnomalyPrompts] = useState(false);
  const [isSavingAlertRules, setIsSavingAlertRules] = useState(false);
  const [banner, setBanner] = useState(null);
  const [rowErrors, setRowErrors] = useState({});
  const [alertRuleErrors, setAlertRuleErrors] = useState({});
  const [busyUploads, setBusyUploads] = useState({});
  const [uploadFeedback, setUploadFeedback] = useState({});
  const [modelOptionCatalog, setModelOptionCatalog] = useState({ model_zoo: null, stages: [] });
  const [defaultBindings, setDefaultBindings] = useState({});
  const [alertRules, setAlertRules] = useState([]);
  const [alertRuleOptions, setAlertRuleOptions] = useState({ sources: [] });
  const [alertRuleLoadHint, setAlertRuleLoadHint] = useState('');
  const [anomalyTextPromptYaml, setAnomalyTextPromptYaml] = useState('');
  const [anomalyTypeYaml, setAnomalyTypeYaml] = useState('');
  const [standardPromptSettings, setStandardPromptSettings] = useState(EMPTY_PROMPT_SETTINGS);
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
  const requestedTab = searchParams.get('tab');
  const activeTab = SETTINGS_TABS.some((tab) => tab.key === requestedTab) ? requestedTab : 'sources';

  useEffect(() => {
    if (!requestedTab || !SETTINGS_TABS.some((tab) => tab.key === requestedTab)) {
      setSearchParams({ tab: 'sources' }, { replace: true });
    }
  }, [requestedTab, setSearchParams]);

  useEffect(() => {
    localStorage.setItem('settingsSourcesDraft', JSON.stringify(sources));
  }, [sources]);

  useEffect(() => {
    localStorage.setItem('settingsLaunchPlanDraft', JSON.stringify(launchPlan));
  }, [launchPlan]);

  const reloadAlertRuleState = async ({ includeRules = true, sourcesSnapshot = [] } = {}) => {
    const requests = [
      fetch(`${BaseURL}/settings/alert-rule-options`),
    ];
    if (includeRules) {
      requests.unshift(fetch(`${BaseURL}/settings/alert-rules`));
    }
    const responses = await Promise.all(requests);
    const firstFailure = responses.find((response) => !response.ok);
    if (firstFailure) {
      let detail = null;
      try {
        const payload = await firstFailure.json();
        detail = payload?.detail || null;
      } catch (error) {
        detail = null;
      }
      setAlertRules([]);
      setAlertRuleOptions({ sources: [] });
      setAlertRuleLoadHint(buildAlertRuleSetupHint(sourcesSnapshot, detail));
      return;
    }
    if (includeRules) {
      const [ruleResponse, optionResponse] = responses;
      const [ruleData, optionData] = await Promise.all([
        ruleResponse.json(),
        optionResponse.json(),
      ]);
      setAlertRules((ruleData || []).map((rule, index) => hydrateAlertRule(rule, index)));
      setAlertRuleOptions(optionData || { sources: [] });
      setAlertRuleLoadHint(buildAlertRuleSetupHint(sourcesSnapshot));
    } else {
      const [optionResponse] = responses;
      const optionData = await optionResponse.json();
      setAlertRuleOptions(optionData || { sources: [] });
      setAlertRuleLoadHint(buildAlertRuleSetupHint(sourcesSnapshot));
    }
  };

  useEffect(() => {
    const loadSources = async () => {
      try {
        const [sourceResponse, modelResponse, bindingResponse] = await Promise.all([
          fetch(`${BaseURL}/settings/input-sources`),
          fetch(`${BaseURL}/model-options`),
          fetch(`${BaseURL}/model-bindings`),
        ]);
        if (!sourceResponse.ok) {
          throw new Error('Failed to load input source settings');
        }
        if (!modelResponse.ok || !bindingResponse.ok) {
          throw new Error('Failed to load model registry settings');
        }
        const [sourceData, modelData, bindingData] = await Promise.all([
          sourceResponse.json(),
          modelResponse.json(),
          bindingResponse.json(),
        ]);
        const hydratedSources = sourceData.length > 0
          ? sourceData.map((source, index) => hydrateSource(source, index))
          : [createSourceDraft()];
        if (sourceData.length > 0) {
          setSources(hydratedSources);
        } else {
          setSources(hydratedSources);
        }
        setModelOptionCatalog(modelData);
        const nextDefaults = {};
        bindingData
          .filter((binding) => binding.binding_scope === 'default')
          .forEach((binding) => {
            nextDefaults[binding.stage] = binding.model_key || '';
          });
        setDefaultBindings(nextDefaults);
        try {
          let standardPromptData = EMPTY_PROMPT_SETTINGS;
          const standardPromptResponse = await fetch(`${BaseURL}/settings/anomaly-prompts/standard`);
          if (standardPromptResponse.ok) {
            standardPromptData = await standardPromptResponse.json();
            setStandardPromptSettings({
              text_prompt_yaml: standardPromptData.text_prompt_yaml || '',
              anomaly_type_yaml: standardPromptData.anomaly_type_yaml || '',
            });
          }
          const promptResponse = await fetch(`${BaseURL}/settings/anomaly-prompts`);
          if (promptResponse.ok) {
            const promptData = await promptResponse.json();
            setAnomalyTextPromptYaml(promptData.text_prompt_yaml || '');
            setAnomalyTypeYaml(promptData.anomaly_type_yaml || '');
          } else {
            setAnomalyTextPromptYaml(standardPromptData.text_prompt_yaml || '');
            setAnomalyTypeYaml(standardPromptData.anomaly_type_yaml || '');
          }
        } catch {
          // Keep model and source controls available even if prompt files are unavailable.
        }
        await reloadAlertRuleState({
          sourcesSnapshot: sourceData,
        });
      } catch (error) {
        setBanner({ kind: 'error', text: error.message });
      }
    };

    loadSources();
  }, []);

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

  const addAlertRule = (sourceId) => {
    setAlertRules((previous) => [
      ...previous,
      createAlertRuleDraft(sourceId, getPreferredSignalFamily(sourceId)),
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

  const setAlertRuleSignalFamily = (clientKey, signalFamily) => {
    setAlertRules((previous) =>
      previous.map((rule) =>
        rule.clientKey === clientKey
          ? {
              ...rule,
              signal_family: signalFamily,
              target_key: '',
            }
          : rule
      )
    );
  };

  const setSourceKind = (clientKey, kind) => {
    setUploadFeedback((previous) => {
      const next = { ...previous };
      delete next[clientKey];
      return next;
    });
    setSources((previous) =>
      previous.map((source, index) => {
        if (source.clientKey !== clientKey) {
          return source;
        }
        return {
          ...source,
          kind,
          upload_id: kind === 'video_upload' ? source.upload_id : null,
          upload: kind === 'video_upload' ? source.upload : null,
          source_value:
            kind === 'webcam'
              ? 0
              : kind === 'video_upload'
                ? null
                : '',
          order: index,
        };
      })
    );
  };

  const addSource = () => {
    setSources((previous) => [...previous, createSourceDraft()]);
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
      if (!source.label.trim()) {
        nextErrors[source.clientKey] = 'Label is required.';
      } else if (source.kind === 'video_upload' && !source.upload_id) {
        nextErrors[source.clientKey] = 'Upload a video file before saving.';
      } else if (source.kind !== 'video_upload' && `${source.source_value ?? ''}`.trim() === '') {
        nextErrors[source.clientKey] = 'Source value is required.';
      }
    });
    setRowErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const validateAlertRules = () => {
    const nextErrors = {};
    alertRules.forEach((rule) => {
      const sourceSignalOptions = getSignalOptionsForSource(rule.source_id, rule.signal_family);
      const validTargets = new Set((sourceSignalOptions?.options || []).map((option) => option.key.toLowerCase()));
      if (!rule.target_key) {
        nextErrors[rule.clientKey] = 'Select a target for the rule.';
      } else if (sourceSignalOptions?.unavailable_reason) {
        nextErrors[rule.clientKey] = sourceSignalOptions.unavailable_reason;
      } else if (!validTargets.has(rule.target_key.toLowerCase())) {
        nextErrors[rule.clientKey] = 'Select a valid target from the prepared options.';
      } else if (Number.isNaN(Number(rule.min_confidence)) || Number(rule.min_confidence) < 0 || Number(rule.min_confidence) > 1) {
        nextErrors[rule.clientKey] = 'Confidence must be between 0.0 and 1.0.';
      }
    });
    setAlertRuleErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const saveDefaultBindings = async () => {
    setIsSavingBindings(true);
    try {
      const payload = MODEL_STAGE_OPTIONS.map((option) => ({
        stage: option.stage,
        model_key: defaultBindings[option.stage] || null,
        binding_scope: 'default',
      }));
      const response = await fetch(`${BaseURL}/model-bindings`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || 'Failed to save default model bindings');
      }
      const nextDefaults = {};
      data
        .filter((binding) => binding.binding_scope === 'default')
        .forEach((binding) => {
          nextDefaults[binding.stage] = binding.model_key || '';
        });
      setDefaultBindings(nextDefaults);
      await reloadAlertRuleState({ includeRules: false, sourcesSnapshot: sources.filter((source) => source.id) });
      setBanner({ kind: 'success', text: 'Default model bindings saved.' });
    } catch (error) {
      setBanner({ kind: 'error', text: error.message });
    } finally {
      setIsSavingBindings(false);
    }
  };

  const saveAnomalyPrompts = async () => {
    setIsSavingAnomalyPrompts(true);
    try {
      const response = await fetch(`${BaseURL}/settings/anomaly-prompts`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          text_prompt_yaml: anomalyTextPromptYaml,
          anomaly_type_yaml: anomalyTypeYaml,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || 'Failed to save anomaly prompts');
      }
      setAnomalyTextPromptYaml(data.text_prompt_yaml || '');
      setAnomalyTypeYaml(data.anomaly_type_yaml || '');
      await reloadAlertRuleState({ includeRules: false, sourcesSnapshot: sources.filter((source) => source.id) });
      setBanner({ kind: 'success', text: 'Anomaly prompts saved.' });
    } catch (error) {
      setBanner({ kind: 'error', text: error.message });
    } finally {
      setIsSavingAnomalyPrompts(false);
    }
  };

  const loadStandardTextPrompt = () => {
    if (!standardPromptSettings.text_prompt_yaml) {
      setBanner({ kind: 'error', text: 'Standard text prompt is unavailable.' });
      return;
    }
    setAnomalyTextPromptYaml(standardPromptSettings.text_prompt_yaml);
    setBanner({ kind: 'success', text: 'Loaded standard text prompt.' });
  };

  const loadStandardAnomalyTypePrompt = () => {
    if (!standardPromptSettings.anomaly_type_yaml) {
      setBanner({ kind: 'error', text: 'Standard anomaly type prompt is unavailable.' });
      return;
    }
    setAnomalyTypeYaml(standardPromptSettings.anomaly_type_yaml);
    setBanner({ kind: 'success', text: 'Loaded standard anomaly type prompt.' });
  };

  const saveSources = async () => {
    if (!validateSources()) {
      setBanner({ kind: 'error', text: 'Fix the highlighted source rows first.' });
      return;
    }

    setIsSaving(true);
    try {
      const response = await fetch(`${BaseURL}/settings/input-sources`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(sanitizeSourcesForApi(sources)),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || 'Failed to save source settings');
      }
      const hydratedSources = data.map((source, index) => hydrateSource(source, index));
      setSources(hydratedSources);
      await reloadAlertRuleState({ sourcesSnapshot: data });
      setBanner({ kind: 'success', text: 'Source settings saved.' });
    } catch (error) {
      setBanner({ kind: 'error', text: error.message });
    } finally {
      setIsSaving(false);
    }
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
      const response = await fetch(`${BaseURL}/settings/input-sources/uploads`, {
        method: 'POST',
        body: formData,
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || 'Failed to upload video');
      }
      setSources((previous) =>
        previous.map((source) =>
          source.clientKey === clientKey
            ? {
                ...source,
                upload_id: data.upload.id,
                upload: data.upload,
                label: source.label || data.upload.original_filename,
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
      setUploadFeedback((previous) => ({
        ...previous,
        [clientKey]: { kind: 'error', text: error.message },
      }));
      setBanner({ kind: 'error', text: error.message });
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
      const response = await fetch(`${BaseURL}/settings/alert-rules`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(sanitizeAlertRulesForApi(alertRules)),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || 'Failed to save alert rules');
      }
      setAlertRules((data || []).map((rule, index) => hydrateAlertRule(rule, index)));
      setAlertRuleErrors({});
      await reloadAlertRuleState({ includeRules: false, sourcesSnapshot: sources.filter((source) => source.id) });
      setBanner({ kind: 'success', text: 'Alert rules saved.' });
    } catch (error) {
      setBanner({ kind: 'error', text: error.message });
    } finally {
      setIsSavingAlertRules(false);
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
  const getDisplayNameForStage = (stage, modelKey, fallbackLabel) => {
    if (!modelKey) {
      return fallbackLabel;
    }
    return modelDisplayNamesByStage[stage]?.[modelKey] || modelKey;
  };
  const alertRulesBySource = sources.reduce((result, source) => {
    result[source.id ?? source.clientKey] = alertRules.filter((rule) => rule.source_id === source.id);
    return result;
  }, {});
  const modelZooSource = modelOptionCatalog.model_zoo || {};
  const modelZooSummary = modelZooSource.commit_short
    ? `Options prepared from model-zoo commit ${modelZooSource.commit_short}${modelZooSource.resolved_from ? ` via ${modelZooSource.resolved_from.replace('_', ' ')}` : ''}.`
    : 'Options prepared from the installed model-zoo catalog.';
  const stageLibraryEntries = MODEL_STAGE_OPTIONS.map((option) => {
    const stageOptions = modelOptionsByStage[option.stage] || [];
    return {
      ...option,
      ...MODEL_STAGE_COPY[option.stage],
      options: stageOptions,
      defaultDisplayName: getDisplayNameForStage(option.stage, defaultBindings[option.stage], 'No default selected'),
    };
  });

  return (
    <div className="settings-container">
      <div className="settings-content">
        <div className="panel-header">
          <div>
            <h2>Settings</h2>
            <p className="panel-subtitle">
              Configure sources, run control, monitoring, and repository initialization from one workspace.
            </p>
          </div>
        </div>
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

        <div className="settings-tab-panel">
          {activeTab === 'sources' && (
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
                        <p>Manage the source queue stored in Postgres for the next run.</p>
                      </div>
                      <button type="button" onClick={addSource} className="secondary-button">
                        Add Source
                      </button>
                    </div>

                    <div className="source-list">
                      {sources.map((source, index) => (
                        <div key={source.clientKey} className="source-row">
                          <div className="source-row-header">
                            <strong>Source {index + 1}</strong>
                            <button
                              type="button"
                              onClick={() => removeSource(source.clientKey)}
                              className="ghost-button"
                            >
                              Remove
                            </button>
                          </div>

                          <div className="source-grid">
                            <label>
                              <span>Type</span>
                              <select
                                value={source.kind}
                                onChange={(event) => setSourceKind(source.clientKey, event.target.value)}
                              >
                                {SOURCE_KIND_OPTIONS.map((option) => (
                                  <option key={option.value} value={option.value}>
                                    {option.label}
                                  </option>
                                ))}
                              </select>
                            </label>

                            <label>
                              <span>Label</span>
                              <input
                                type="text"
                                value={source.label}
                                onChange={(event) => setSourceField(source.clientKey, 'label', event.target.value)}
                                placeholder="Checkpoint A"
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

                            <label className="toggle-field">
                              <span>{DEFAULT_SOURCE_ENABLE_LABEL}</span>
                              <input
                                type="checkbox"
                                checked={source.enabled}
                                onChange={(event) => setSourceField(source.clientKey, 'enabled', event.target.checked)}
                              />
                            </label>
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
                                    Use default ({getDisplayNameForStage(option.stage, defaultBindings[option.stage], 'None')})
                                  </option>
                                  {(modelOptionsByStage[option.stage] || []).map((registration) => (
                                    <option key={registration.model_key} value={registration.model_key}>
                                      {registration.display_name || registration.model_key}
                                    </option>
                                  ))}
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
                        {isSaving ? 'Saving...' : 'Save Source Settings'}
                      </button>
                    </div>
                  </div>
                </div>

                <div className="control-column">
                  <div className="card">
                    <div className="card-header">
                      <div>
                        <h3>Default Model Bindings</h3>
                        <p>Set default detector, tracker, ReID, anomaly Stage 1, and anomaly Stage 2 models for new runs.</p>
                        <p className="muted-text">{modelZooSummary}</p>
                      </div>
                    </div>
                    <div className="model-binding-grid">
                      {MODEL_STAGE_OPTIONS.map((option) => (
                        <label key={option.stage}>
                          <span>{option.label}</span>
                          <select
                            value={defaultBindings[option.stage] || ''}
                            onChange={(event) => setDefaultBindings((previous) => ({
                              ...previous,
                              [option.stage]: event.target.value,
                            }))}
                          >
                            <option value="">No default</option>
                            {(modelOptionsByStage[option.stage] || []).map((registration) => (
                              <option key={registration.model_key} value={registration.model_key}>
                                {registration.display_name || registration.model_key}
                              </option>
                            ))}
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
                        <h3>Anomaly Prompt Settings</h3>
                        <p>Edit the text template and anomaly type prompt lists used by Stage 2 anomaly enrichment.</p>
                      </div>
                    </div>
                    <div className="model-binding-grid">
                      <label>
                        <span>Text Prompt YAML</span>
                        <textarea
                          value={anomalyTextPromptYaml}
                          onChange={(event) => setAnomalyTextPromptYaml(event.target.value)}
                          rows={10}
                        />
                      </label>
                      <label>
                        <span>Anomaly Type YAML</span>
                        <textarea
                          value={anomalyTypeYaml}
                          onChange={(event) => setAnomalyTypeYaml(event.target.value)}
                          rows={10}
                        />
                      </label>
                    </div>
                    <div className="control-actions">
                      <button
                        type="button"
                        onClick={loadStandardTextPrompt}
                        className="secondary-button"
                        disabled={!standardPromptSettings.text_prompt_yaml}
                      >
                        Use Standard Text Prompt
                      </button>
                      <button
                        type="button"
                        onClick={loadStandardAnomalyTypePrompt}
                        className="secondary-button"
                        disabled={!standardPromptSettings.anomaly_type_yaml}
                      >
                        Use Standard Anomaly Type Prompt
                      </button>
                      <button
                        type="button"
                        onClick={saveAnomalyPrompts}
                        className="secondary-button"
                        disabled={isSavingAnomalyPrompts}
                      >
                        {isSavingAnomalyPrompts ? 'Saving...' : 'Save Anomaly Prompts'}
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
                      <div className="muted-text">GET/PUT {`${BaseURL}/settings/anomaly-prompts`}</div>
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
          )}

          {activeTab === 'model-library' && (
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
                              <span>Default: {stage.defaultDisplayName}</span>
                            </div>
                          </div>

                          {stage.options.length === 0 ? (
                            <div className="empty-state">No {stage.label.toLowerCase()} models are currently registered.</div>
                          ) : (
                            <div className="model-library-grid">
                              {stage.options.map((option) => {
                                const detectorClasses = getModelClasses(option);
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
                                          Available detector classes include {formatListLabel(detectorClasses)}.
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
                                        <span>{option.requires_gpu ? 'GPU' : 'CPU or GPU'}</span>
                                      </div>
                                      <div className="model-library-fact">
                                        <span className="model-library-fact-label">Backend</span>
                                        <span>{backend || 'catalog entry'}</span>
                                      </div>
                                      {option.stage === 'detector' && detectorClasses.length > 0 && (
                                        <div className="model-library-fact">
                                          <span className="model-library-fact-label">Available Classes</span>
                                          <span>{formatListLabel(detectorClasses)}</span>
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
          )}

          {activeTab === 'alerts' && (
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
                        <h3>Triggered Alerts</h3>
                        <p>Define single-condition alert rules per source, using detector classes or anomaly prompt lists.</p>
                      </div>
                    </div>

                    <div className="source-list">
                      {alertRuleLoadHint && (
                        <div className="empty-state">{alertRuleLoadHint}</div>
                      )}

                      {sources.map((source, index) => {
                        const sourceOption = alertRuleOptionsBySource[source.id];
                        const signalOptions = sourceOption?.signal_options || [];
                        const sourceRules = alertRulesBySource[source.id] || [];
                        return (
                          <div key={source.clientKey} className="source-row">
                            <div className="source-row-header">
                              <div>
                                <strong>{source.label || `Source ${index + 1}`}</strong>
                                <div className="muted-text">
                                  {getDisplayNameForStage('detector', source.detector_model_key || defaultBindings.detector, 'No Detector')} · {getDisplayNameForStage('anomaly_stage_1', source.anomaly_stage_1_model_key || defaultBindings.anomaly_stage_1, 'No Anomaly Stage 1')} · {getDisplayNameForStage('anomaly_stage_2', source.anomaly_stage_2_model_key || defaultBindings.anomaly_stage_2, 'No Anomaly Stage 2')}
                                </div>
                              </div>
                              <button
                                type="button"
                                onClick={() => source.id && addAlertRule(source.id)}
                                className="secondary-button"
                                disabled={!source.id}
                              >
                                Add Rule
                              </button>
                            </div>

                            {signalOptions.length > 0 && (
                              <div className="alert-option-grid">
                                {signalOptions.map((signalOption) => (
                                  <div key={`${source.id}-${signalOption.signal_family}`} className="empty-state">
                                    <strong>
                                      {ALERT_SIGNAL_FAMILY_OPTIONS.find((option) => option.value === signalOption.signal_family)?.label || signalOption.signal_family}
                                    </strong>
                                    {signalOption.unavailable_reason ? (
                                      <div className="muted-text">{signalOption.unavailable_reason}</div>
                                    ) : (
                                      <div className="muted-text">
                                        {(signalOption.options || []).map((option) => option.label).join(', ') || 'No options available'}
                                      </div>
                                    )}
                                  </div>
                                ))}
                              </div>
                            )}

                            {sourceRules.length === 0 ? (
                              <div className="empty-state">No alert rules for this source yet.</div>
                            ) : (
                              <div className="source-list">
                                {sourceRules.map((rule, ruleIndex) => {
                                  const selectedSignalOptions = getSignalOptionsForSource(rule.source_id, rule.signal_family);
                                  const targetOptions = selectedSignalOptions?.options || [];
                                  return (
                                    <div key={rule.clientKey} className="source-row">
                                      <div className="source-row-header">
                                        <strong>Rule {ruleIndex + 1}</strong>
                                        <button
                                          type="button"
                                          onClick={() => removeAlertRule(rule.clientKey)}
                                          className="ghost-button"
                                        >
                                          Remove
                                        </button>
                                      </div>

                                      <div className="model-binding-grid">
                                        <label>
                                          <span>Rule Label</span>
                                          <input
                                            type="text"
                                            value={rule.rule_label}
                                            onChange={(event) => setAlertRuleField(rule.clientKey, 'rule_label', event.target.value)}
                                            placeholder="Optional operator label"
                                          />
                                        </label>
                                        <label>
                                          <span>Signal</span>
                                          <select
                                            value={rule.signal_family}
                                            onChange={(event) => setAlertRuleSignalFamily(rule.clientKey, event.target.value)}
                                          >
                                            {ALERT_SIGNAL_FAMILY_OPTIONS.map((option) => (
                                              <option key={option.value} value={option.value}>
                                                {option.label}
                                              </option>
                                            ))}
                                          </select>
                                        </label>
                                        <label>
                                          <span>Target</span>
                                          <select
                                            value={rule.target_key}
                                            onChange={(event) => setAlertRuleField(rule.clientKey, 'target_key', event.target.value)}
                                            disabled={Boolean(selectedSignalOptions?.unavailable_reason)}
                                          >
                                            <option value="">
                                              {selectedSignalOptions?.unavailable_reason ? 'Unavailable' : 'Select target'}
                                            </option>
                                            {targetOptions.map((option) => (
                                              <option key={option.key} value={option.key}>
                                                {option.label}
                                              </option>
                                            ))}
                                          </select>
                                        </label>
                                        <label>
                                          <span>Min Confidence</span>
                                          <input
                                            type="number"
                                            min="0"
                                            max="1"
                                            step="0.01"
                                            value={rule.min_confidence}
                                            onChange={(event) => setAlertRuleField(rule.clientKey, 'min_confidence', event.target.value)}
                                          />
                                        </label>
                                        <label>
                                          <span>Alert Level</span>
                                          <select
                                            value={rule.alert_level}
                                            onChange={(event) => setAlertRuleField(rule.clientKey, 'alert_level', event.target.value)}
                                          >
                                            {ALERT_LEVEL_OPTIONS.map((option) => (
                                              <option key={option.value} value={option.value}>
                                                {option.label}
                                              </option>
                                            ))}
                                          </select>
                                        </label>
                                        <label className="toggle-field">
                                          <span>Enabled</span>
                                          <input
                                            type="checkbox"
                                            checked={rule.enabled}
                                            onChange={(event) => setAlertRuleField(rule.clientKey, 'enabled', event.target.checked)}
                                          />
                                        </label>
                                      </div>

                                      {alertRuleErrors[rule.clientKey] && (
                                        <div className="row-error">{alertRuleErrors[rule.clientKey]}</div>
                                      )}
                                    </div>
                                  );
                                })}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>

                    <div className="control-actions">
                      <button type="button" onClick={saveAlertRules} className="secondary-button" disabled={isSavingAlertRules}>
                        {isSavingAlertRules ? 'Saving...' : 'Save Alert Rules'}
                      </button>
                    </div>
                  </div>
                </div>

                <div className="control-column">
                  <div className="card">
                    <div className="card-header">
                      <div>
                        <h3>How It Works</h3>
                        <p>Each rule watches one source and one signal family. When the target is present above the confidence threshold, the system creates an `ALERT` incident.</p>
                      </div>
                    </div>
                    <div className="empty-state endpoint-info">
                      <strong>GET {`${BaseURL}/settings/alert-rule-options`}</strong>
                      <div className="muted-text">Prepared source-specific detector, anomaly object, and anomaly activity targets.</div>
                      <div className="muted-text">GET/PUT {`${BaseURL}/settings/alert-rules`}</div>
                      <div className="muted-text">Rules are evaluated per source during live detector and anomaly processing.</div>
                    </div>
                  </div>
                </div>
              </section>
            </>
          )}

          {activeTab === 'run' && <RunSection embedded pollingEnabled />}
          {activeTab === 'monitoring' && <MonitoringSection embedded pollingEnabled />}

          {activeTab === 'initialization' && (
            <div className="control-column">
              <div className="card">
                <div className="card-header">
                  <div>
                    <h3>Repository Initialization</h3>
                    <p>Prepare the command-line launch plan for this host and deployment profile.</p>
                  </div>
                </div>
                <div className="model-binding-grid">
                  <label>
                    <span>Service Mode</span>
                    <select
                      value={launchPlan.mode}
                      onChange={(event) => setLaunchPlan((previous) => ({ ...previous, mode: event.target.value }))}
                    >
                      <option value="api">api</option>
                      <option value="pipeline">pipeline</option>
                    </select>
                  </label>
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
                  <div className="muted-text">4. Save sources and model bindings here before pressing Start in the Run tab.</div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default SettingsPage;
