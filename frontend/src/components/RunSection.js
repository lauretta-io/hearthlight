import React, { useEffect, useState } from 'react';
import { BaseURL } from '../config';
import {
  formatUploadedVideoSummary,
  SUPPORTED_VIDEO_LABEL,
  validateSelectedVideoFile,
  VIDEO_UPLOAD_ACCEPT,
} from '../utils/videoUpload';
import '../styles/CameraConfig.css';

const TASK_OPTIONS = ['PERSON', 'BAG'];
const MODULES = ['INGESTOR', 'REID', 'ASSOCIATION'];
const SOURCE_KIND_OPTIONS = [
  { value: 'camera_url', label: 'Camera URL' },
  { value: 'video_upload', label: 'Uploaded Video' },
  { value: 'webcam', label: 'Webcam' },
];

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

const createSourceDraft = (kind = 'camera_url') => ({
  clientKey: `source-${Date.now()}-${Math.random().toString(16).slice(2)}`,
  id: null,
  kind,
  label: '',
  tasks: [...TASK_OPTIONS],
  enabled: true,
  order: 0,
  source_value: kind === 'webcam' ? 0 : '',
  upload_id: null,
  upload: null,
});

const hydrateSource = (source, fallbackIndex = 0) => ({
  clientKey: source.id ? `source-${source.id}` : `source-${fallbackIndex}-${Math.random().toString(16).slice(2)}`,
  id: source.id ?? null,
  kind: source.kind ?? 'camera_url',
  label: source.label ?? '',
  tasks: source.tasks ?? [...TASK_OPTIONS],
  enabled: source.enabled ?? true,
  order: source.order ?? fallbackIndex,
  source_value:
    source.source_value ??
    (source.kind === 'webcam' ? 0 : ''),
  upload_id: source.upload_id ?? null,
  upload: source.upload ?? null,
  state: source.state ?? 'idle',
  frames_processed: source.frames_processed ?? null,
  total_frames: source.total_frames ?? null,
  fps: source.fps ?? null,
  last_error: source.last_error ?? null,
  last_activity_at: source.last_activity_at ?? null,
});

const sanitizeSourcesForApi = (sources) =>
  sources.map((source, index) => ({
    id: source.id ?? undefined,
    kind: source.kind,
    label: source.label.trim() || defaultSourceLabel(source, index, sources),
    tasks: source.tasks,
    enabled: source.enabled,
    order: index,
    source_value: source.kind === 'video_upload' ? null : source.source_value,
    upload_id: source.kind === 'video_upload' ? source.upload_id : null,
  }));

const sourcePlaceholder = (kind) => {
  if (kind === 'webcam') {
    return 'Device index, e.g. 0';
  }
  return 'rtsp://, http://, or stream URL';
};

const formatPercent = (value) => (
  value === null || value === undefined ? 'n/a' : `${value.toFixed(1)}%`
);

const dependencyEntries = (dependencyStatus) => Object.entries(dependencyStatus || {});
const moduleMetricEntries = (moduleMetrics) => Object.entries(moduleMetrics || {});

const RunSection = ({ embedded = false, pollingEnabled = true }) => {
  const [sources, setSources] = useState(() => {
    const saved = localStorage.getItem('controlSourcesDraft');
    if (!saved) {
      return [createSourceDraft()];
    }
    try {
      return JSON.parse(saved);
    } catch (error) {
      return [createSourceDraft()];
    }
  });
  const [statusData, setStatusData] = useState({
    status: 'idle',
    sources: [],
    module_status: {},
    admission: null,
    run_id: null,
  });
  const [resourceData, setResourceData] = useState({
    cpu_percent: null,
    memory_percent: null,
    disk_percent: null,
    gpus: [],
    dependency_status: {},
    module_status: {},
    admission: null,
  });
  const [isSaving, setIsSaving] = useState(false);
  const [banner, setBanner] = useState(null);
  const [rowErrors, setRowErrors] = useState({});
  const [busyUploads, setBusyUploads] = useState({});
  const [uploadFeedback, setUploadFeedback] = useState({});

  useEffect(() => {
    localStorage.setItem('controlSourcesDraft', JSON.stringify(sources));
  }, [sources]);

  useEffect(() => {
    if (!pollingEnabled) {
      return undefined;
    }

    const loadSources = async () => {
      try {
        const response = await fetch(`${BaseURL}/sources`);
        if (!response.ok) {
          throw new Error('Failed to load sources');
        }
        const data = await response.json();
        if (data.length > 0) {
          setSources(data.map((source, index) => hydrateSource(source, index)));
        }
      } catch (error) {
        console.error(error);
      }
    };

    const loadStatus = async () => {
      try {
        const response = await fetch(`${BaseURL}/status`);
        if (!response.ok) {
          throw new Error('Failed to fetch status');
        }
        const data = await response.json();
        setStatusData(data);
      } catch (error) {
        setStatusData((previous) => ({
          ...previous,
          status: 'error',
        }));
      }
    };

    const loadResources = async () => {
      try {
        const response = await fetch(`${BaseURL}/system/resources`);
        if (!response.ok) {
          throw new Error('Failed to fetch resources');
        }
        const data = await response.json();
        setResourceData(data);
      } catch (error) {
        console.error(error);
      }
    };

    loadSources();
    loadStatus();
    loadResources();

    const intervalId = window.setInterval(() => {
      loadStatus();
      loadResources();
    }, 2000);

    return () => window.clearInterval(intervalId);
  }, [pollingEnabled]);

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
      if (source.tasks.length === 0) {
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

  const saveSources = async () => {
    if (!validateSources()) {
      throw new Error('Fix the highlighted source rows first');
    }

    setIsSaving(true);
    try {
      const response = await fetch(`${BaseURL}/sources`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(sanitizeSourcesForApi(sources)),
      });

      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        throw new Error(errorBody.detail || 'Failed to save sources');
      }

      const data = await response.json();
      setSources(data.map((source, index) => hydrateSource(source, index)));
      setBanner({ kind: 'success', text: 'Source queue saved.' });
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
      const response = await fetch(`${BaseURL}/sources/uploads`, {
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
      setUploadFeedback((previous) => ({
        ...previous,
        [clientKey]: { kind: 'error', text: error.message },
      }));
      setBanner({ kind: 'error', text: error.message });
    } finally {
      setBusyUploads((previous) => ({ ...previous, [clientKey]: false }));
    }
  };

  const handleStart = async () => {
    try {
      await saveSources();
      const response = await fetch(`${BaseURL}/start`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || 'Failed to start system');
      }
      setBanner({ kind: 'success', text: `Run ${data.run_id} is starting.` });
    } catch (error) {
      setBanner({ kind: 'error', text: error.message });
    }
  };

  const handleStop = async () => {
    try {
      const response = await fetch(`${BaseURL}/stop`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || 'Failed to stop system');
      }
      setBanner({ kind: 'success', text: `System ${data.status}.` });
    } catch (error) {
      setBanner({ kind: 'error', text: error.message });
    }
  };

  const handleRestartModule = async (moduleName) => {
    try {
      const response = await fetch(`${BaseURL}/system/modules/${moduleName}/restart`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || `Failed to restart ${moduleName}`);
      }
      setBanner({ kind: 'success', text: `${data.module} restart requested.` });
    } catch (error) {
      setBanner({ kind: 'error', text: error.message });
    }
  };

  const resourceAdmission = resourceData.admission || statusData.admission;
  const dependencyStatus = dependencyEntries(resourceData.dependency_status || statusData.resources?.dependency_status);
  const moduleMetrics = moduleMetricEntries(resourceData.module_metrics || statusData.resources?.module_metrics);
  const moduleMetricsByName = Object.fromEntries(moduleMetrics);
  const liveSources = statusData.sources || [];

  const content = (
    <>
      <div className="panel-header">
        <div>
          <h2>Run Control</h2>
          <p className="panel-subtitle">
            Combine live cameras, uploaded video, and webcams in a single run.
          </p>
        </div>
        <div className="run-meta">
          <span className={`status-pill status-${statusData.status}`}>
            {statusData.status}
          </span>
          <span className="run-id">
            {statusData.run_id ? `Run ${statusData.run_id}` : 'No active run'}
          </span>
        </div>
      </div>

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
                <h3>Source Queue</h3>
                <p>Persisted to Postgres and merged into the runtime config at start.</p>
              </div>
              <button type="button" onClick={addSource} className="secondary-button">
                Add Source
              </button>
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

                  {rowErrors[source.clientKey] && (
                    <div className="row-error">{rowErrors[source.clientKey]}</div>
                  )}
                </div>
              ))}
            </div>

            <div className="control-actions">
              <button type="button" onClick={saveSources} className="secondary-button" disabled={isSaving}>
                {isSaving ? 'Saving...' : 'Save Sources'}
              </button>
              <button type="button" onClick={handleStart} className="start-button" disabled={isSaving}>
                Start
              </button>
              <button type="button" onClick={handleStop} className="stop-button">
                Stop
              </button>
            </div>
          </div>
        </div>

        <div className="control-column">
          <div className="card">
            <div className="card-header">
              <div>
                <h3>Processing State</h3>
                <p>Per-source view of the active queue.</p>
              </div>
            </div>
            <div className="status-list">
              {liveSources.length === 0 && (
                <div className="empty-state">No sources are active yet.</div>
              )}
              {liveSources.map((source) => (
                <div key={`live-${source.id ?? source.label}`} className="status-row">
                  <div>
                    <strong>{source.label}</strong>
                    <div className="muted-text">{source.kind}</div>
                  </div>
                  <div className="status-row-meta">
                    <span className={`status-pill status-${source.state}`}>{source.state}</span>
                    <span className="muted-text">
                      {source.frames_processed !== null && source.frames_processed !== undefined
                        ? `${source.frames_processed}${source.total_frames ? ` / ${source.total_frames}` : ''} frames`
                        : 'No frame data'}
                    </span>
                  </div>
                  {source.last_error && (
                    <div className="row-error">{source.last_error}</div>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <div className="card-header">
              <div>
                <h3>Resources And Admission</h3>
                <p>Start gating and module controls.</p>
              </div>
            </div>

            <div className="metric-grid">
              <div className="metric-card">
                <span>CPU</span>
                <strong>{formatPercent(resourceData.cpu_percent)}</strong>
              </div>
              <div className="metric-card">
                <span>Memory</span>
                <strong>{formatPercent(resourceData.memory_percent)}</strong>
              </div>
              <div className="metric-card">
                <span>Disk</span>
                <strong>{formatPercent(resourceData.disk_percent)}</strong>
              </div>
              <div className="metric-card">
                <span>GPU</span>
                <strong>{resourceData.gpus?.length ? `${resourceData.gpus.length} detected` : 'None'}</strong>
              </div>
            </div>

            <div className={`admission-box ${resourceAdmission?.allowed ? 'admission-allowed' : 'admission-blocked'}`}>
              <strong>{resourceAdmission?.allowed ? 'Admission open' : 'Admission blocked'}</strong>
              <span>{resourceAdmission?.reason || 'Resources and modules look healthy.'}</span>
            </div>

            <div className="dependency-list">
              {dependencyStatus.map(([name, dependency]) => (
                <div key={name} className="dependency-row">
                  <strong>{name}</strong>
                  <span className={`status-pill status-${dependency.status === 'ok' ? 'running' : 'error'}`}>
                    {dependency.status}
                  </span>
                  <span className="muted-text">{dependency.detail || 'healthy'}</span>
                </div>
              ))}
            </div>

            {resourceData.gpus?.length > 0 && (
              <div className="gpu-list">
                {resourceData.gpus.map((gpu) => (
                  <div key={gpu.index} className="gpu-row">
                    <strong>{gpu.name}</strong>
                    <span>{formatPercent(gpu.utilization_percent)}</span>
                    <span>
                      {gpu.memory_used_mb && gpu.memory_total_mb
                        ? `${gpu.memory_used_mb.toFixed(0)} / ${gpu.memory_total_mb.toFixed(0)} MB`
                        : 'n/a'}
                    </span>
                  </div>
                ))}
              </div>
            )}

            <div className="module-list">
              {MODULES.map((moduleName) => (
                <div key={moduleName} className="module-row">
                  <div>
                    <strong>{moduleName}</strong>
                    <div className="muted-text">
                      {statusData.module_status?.[moduleName] || resourceData.module_status?.[moduleName] || 'unknown'}
                    </div>
                    {moduleMetricsByName[moduleName] && (
                      <div className="muted-text">
                        Queue state {moduleMetricsByName[moduleName].state}
                        {moduleMetricsByName[moduleName].hottest_queue
                          ? ` · hottest ${moduleMetricsByName[moduleName].hottest_queue} (${moduleMetricsByName[moduleName].max_queue_depth})`
                          : ''}
                      </div>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => handleRestartModule(moduleName)}
                    className="secondary-button"
                  >
                    Restart
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>
    </>
  );

  if (embedded) {
    return content;
  }

  return (
    <div className="settings-container">
      <div className="settings-content">
        {content}
      </div>
    </div>
  );
};

export default RunSection;
