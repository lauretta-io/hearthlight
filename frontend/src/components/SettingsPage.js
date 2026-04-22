import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { BaseURL } from '../config';
import RunSection from './RunSection';
import MonitoringSection from './MonitoringSection';
import '../styles/CameraConfig.css';

const TASK_OPTIONS = ['PERSON', 'BAG', 'GUN'];
const SOURCE_KIND_OPTIONS = [
  { value: 'camera_url', label: 'Camera URL' },
  { value: 'video_upload', label: 'Uploaded Video' },
  { value: 'webcam', label: 'Webcam' },
];
const MODEL_STAGE_OPTIONS = [
  { stage: 'detector', label: 'Detector', field: 'detector_model_key' },
  { stage: 'tracker', label: 'Tracker', field: 'tracker_model_key' },
  { stage: 'reid', label: 'Person ReID', field: 'reid_model_key' },
  { stage: 'anomaly', label: 'Anomaly', field: 'anomaly_model_key' },
];
const TEMPLATE_OPTIONS = ['active', 'example', 'master_config', 'office_config'];
const SETTINGS_TABS = [
  { key: 'sources', label: 'Sources' },
  { key: 'run', label: 'Run' },
  { key: 'monitoring', label: 'Monitoring' },
  { key: 'initialization', label: 'Initialization' },
];

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
  anomaly_model_key: null,
});

const hydrateSource = (source, fallbackIndex = 0) => ({
  clientKey: source.id ? `settings-source-${source.id}` : `settings-source-${fallbackIndex}-${Math.random().toString(16).slice(2)}`,
  id: source.id ?? null,
  kind: source.kind ?? 'camera_url',
  label: source.label ?? '',
  tasks: source.tasks ?? [...TASK_OPTIONS],
  enabled: source.enabled ?? true,
  order: source.order ?? fallbackIndex,
  source_value: source.source_value ?? (source.kind === 'webcam' ? 0 : ''),
  upload_id: source.upload_id ?? null,
  upload: source.upload ?? null,
  detector_model_key: source.detector_model_key ?? null,
  tracker_model_key: source.tracker_model_key ?? null,
  reid_model_key: source.reid_model_key ?? null,
  anomaly_model_key: source.anomaly_model_key ?? null,
});

const sanitizeSourcesForApi = (sources) =>
  sources.map((source, index) => ({
    id: source.id ?? undefined,
    kind: source.kind,
    label: source.label.trim() || `Source ${index + 1}`,
    tasks: source.tasks,
    enabled: source.enabled,
    order: index,
    source_value: source.kind === 'video_upload' ? null : source.source_value,
    upload_id: source.kind === 'video_upload' ? source.upload_id : null,
    detector_model_key: source.detector_model_key || null,
    tracker_model_key: source.tracker_model_key || null,
    reid_model_key: source.reid_model_key || null,
    anomaly_model_key: source.anomaly_model_key || null,
  }));

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
  const [banner, setBanner] = useState(null);
  const [rowErrors, setRowErrors] = useState({});
  const [busyUploads, setBusyUploads] = useState({});
  const [modelRegistrations, setModelRegistrations] = useState([]);
  const [defaultBindings, setDefaultBindings] = useState({});
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

  useEffect(() => {
    const loadSources = async () => {
      try {
        const [sourceResponse, modelResponse, bindingResponse] = await Promise.all([
          fetch(`${BaseURL}/settings/input-sources`),
          fetch(`${BaseURL}/models`),
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
        if (sourceData.length > 0) {
          setSources(sourceData.map((source, index) => hydrateSource(source, index)));
        }
        setModelRegistrations(modelData);
        const nextDefaults = {};
        bindingData
          .filter((binding) => binding.binding_scope === 'default')
          .forEach((binding) => {
            nextDefaults[binding.stage] = binding.model_key || '';
          });
        setDefaultBindings(nextDefaults);
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

  const setSourceKind = (clientKey, kind) => {
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

  const toggleTask = (clientKey, task) => {
    setSources((previous) =>
      previous.map((source) => {
        if (source.clientKey !== clientKey) {
          return source;
        }
        const tasks = source.tasks.includes(task)
          ? source.tasks.filter((value) => value !== task)
          : [...source.tasks, task];
        return {
          ...source,
          tasks,
        };
      })
    );
  };

  const addSource = () => {
    setSources((previous) => [...previous, createSourceDraft()]);
  };

  const removeSource = (clientKey) => {
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
      } else if (source.tasks.length === 0) {
        nextErrors[source.clientKey] = 'Select at least one task.';
      } else if (source.kind === 'video_upload' && !source.upload_id) {
        nextErrors[source.clientKey] = 'Upload a video file before saving.';
      } else if (source.kind !== 'video_upload' && `${source.source_value ?? ''}`.trim() === '') {
        nextErrors[source.clientKey] = 'Source value is required.';
      }
    });
    setRowErrors(nextErrors);
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
      setBanner({ kind: 'success', text: 'Default model bindings saved.' });
    } catch (error) {
      setBanner({ kind: 'error', text: error.message });
    } finally {
      setIsSavingBindings(false);
    }
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
      setSources(data.map((source, index) => hydrateSource(source, index)));
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
    setBusyUploads((previous) => ({ ...previous, [clientKey]: true }));
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
      setBanner({ kind: 'success', text: `Uploaded ${data.upload.original_filename}.` });
    } catch (error) {
      setBanner({ kind: 'error', text: error.message });
    } finally {
      setBusyUploads((previous) => ({ ...previous, [clientKey]: false }));
    }
  };

  const registrationsByStage = MODEL_STAGE_OPTIONS.reduce((result, option) => {
    result[option.stage] = modelRegistrations.filter((registration) => registration.stage === option.stage);
    return result;
  }, {});

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
                                  accept="video/*"
                                  onChange={(event) => handleUpload(source.clientKey, event.target.files?.[0])}
                                />
                                <small>
                                  {busyUploads[source.clientKey]
                                    ? 'Uploading...'
                                    : source.upload
                                      ? `${source.upload.original_filename} (${Math.round(source.upload.size_bytes / 1024 / 1024)} MB)`
                                      : 'Choose a video file'}
                                </small>
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
                              <span>Enabled</span>
                              <input
                                type="checkbox"
                                checked={source.enabled}
                                onChange={(event) => setSourceField(source.clientKey, 'enabled', event.target.checked)}
                              />
                            </label>
                          </div>

                          <div className="task-list">
                            {TASK_OPTIONS.map((task) => (
                              <label key={task} className={`task-chip ${source.tasks.includes(task) ? 'task-chip-active' : ''}`}>
                                <input
                                  type="checkbox"
                                  checked={source.tasks.includes(task)}
                                  onChange={() => toggleTask(source.clientKey, task)}
                                />
                                <span>{task}</span>
                              </label>
                            ))}
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
                                    Use default {defaultBindings[option.stage] ? `(${defaultBindings[option.stage]})` : '(none)'}
                                  </option>
                                  {(registrationsByStage[option.stage] || []).map((registration) => (
                                    <option key={registration.model_key} value={registration.model_key}>
                                      {registration.model_key}
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
                        <p>Set the default detector, tracker, ReID, and anomaly models for new runs.</p>
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
                            {(registrationsByStage[option.stage] || []).map((registration) => (
                              <option key={registration.model_key} value={registration.model_key}>
                                {registration.model_key}
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
                        <h3>Integration Endpoint</h3>
                        <p>Other systems can append a source directly.</p>
                      </div>
                    </div>
                    <div className="empty-state">
                      <strong>POST {`${BaseURL}/settings/input-sources`}</strong>
                      <div className="muted-text">
                        Send an `InputSource` JSON payload to add a camera stream, webcam, or uploaded video reference.
                      </div>
                      <div className="muted-text">GET {`${BaseURL}/models`}</div>
                      <div className="muted-text">GET/PUT {`${BaseURL}/model-bindings`}</div>
                    </div>
                  </div>

                  <div className="card">
                    <div className="card-header">
                      <div>
                        <h3>Upload Endpoint</h3>
                        <p>Stage video before attaching it to a source.</p>
                      </div>
                    </div>
                    <div className="empty-state">
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
