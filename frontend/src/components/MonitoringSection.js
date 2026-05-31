import React, { useEffect, useState } from 'react';
import { BaseURL } from '../config';
import { formatDateTime } from '../utils/time';
import { subscribeToOperationsEvent } from '../utils/sharedEvents';
import { subscribeToSharedPoll } from '../utils/sharedPolling';
import '../styles/MonitoringPage.css';

const formatPercent = (value) => (
  value === null || value === undefined ? 'n/a' : `${value.toFixed(1)}%`
);

const endpointURL = (path) => `${BaseURL}${path}`;
const STAGE_LABELS = {
  detector: 'Detector',
  tracker: 'Tracker',
  anomaly_stage_1: 'Heuristic Filter',
  anomaly_stage_2: 'Anomaly Detection',
};
const normalizeSourceKindLabel = (kind) => {
  if (kind === 'camera_url') return 'Camera URL';
  if (kind === 'video_upload') return 'Uploaded Video';
  if (kind === 'webcam') return 'Webcam';
  return kind || 'Unknown';
};
const describeFrameProcessing = (source) => {
  if (source.kind === 'video_upload') {
    return `Every ${source.effective_process_every_n_frames || source.process_every_n_frames || 1} frame(s)`;
  }
  if ((source.frame_processing_mode || 'frame_skip') === 'target_frame_rate') {
    return `Target ${source.target_frame_rate || 5} FPS`;
  }
  return `Every ${source.effective_process_every_n_frames || source.process_every_n_frames || 1} frame(s)`;
};
const sanitizeSourcesForApi = (sources) => sources.map((source, index) => ({
  id: source.id ?? undefined,
  kind: source.kind,
  label: source.label,
  tasks: Array.isArray(source.tasks) && source.tasks.length > 0 ? source.tasks : ['PERSON', 'BAG'],
  enabled: Boolean(source.enabled),
  order: Number.isFinite(source.order) ? source.order : index,
  source_value: source.kind === 'video_upload' ? null : source.source_value,
  upload_id: source.kind === 'video_upload' ? source.upload_id : null,
  frame_processing_mode: source.kind === 'video_upload' ? 'frame_skip' : (source.frame_processing_mode || 'frame_skip'),
  process_every_n_frames: source.kind === 'video_upload'
    ? Math.max(1, Number(source.process_every_n_frames) || 1)
    : (source.frame_processing_mode || 'frame_skip') === 'target_frame_rate'
    ? 1
    : Math.max(1, Number(source.process_every_n_frames) || 1),
  target_frame_rate: source.kind === 'video_upload'
    ? null
    : (source.frame_processing_mode || 'frame_skip') === 'target_frame_rate'
    ? Math.max(0.1, Number(source.target_frame_rate) || 5)
    : null,
  detector_model_key: source.detector_model_key || null,
  tracker_model_key: source.tracker_model_key || null,
  reid_model_key: null,
  anomaly_stage_1_model_key: source.anomaly_stage_1_model_key || null,
  anomaly_stage_2_model_key: source.anomaly_stage_2_model_key || null,
}));

const MonitoringSection = ({ embedded = false, pollingEnabled = true }) => {
  const [overview, setOverview] = useState(null);
  const [mountedModelKeys, setMountedModelKeys] = useState(new Set());
  const [selectedRunIdentifier, setSelectedRunIdentifier] = useState('');
  const [error, setError] = useState(null);
  const [banner, setBanner] = useState(null);
  const [busySourceId, setBusySourceId] = useState(null);
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    let isMounted = true;

    const loadMountedModels = async () => {
      try {
        const response = await fetch(`${BaseURL}/mounted-models`);
        if (!response.ok) {
          throw new Error('Failed to load mounted models');
        }
        const data = await response.json();
        if (!isMounted) {
          return;
        }
        const nextKeys = new Set();
        (Array.isArray(data) ? data : []).forEach((stageEntry) => {
          (stageEntry?.mounted_model_keys || []).forEach((modelKey) => {
            if (modelKey) {
              nextKeys.add(modelKey);
            }
          });
        });
        setMountedModelKeys(nextKeys);
      } catch (_fetchError) {
        if (isMounted) {
          setMountedModelKeys(new Set());
        }
      }
    };

    loadMountedModels();
    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    if (!pollingEnabled) {
      return undefined;
    }

    let isMounted = true;

    const loadOverview = async () => {
      try {
        const params = new URLSearchParams({ limit: '8' });
        if (selectedRunIdentifier) {
          params.set('run_identifier', selectedRunIdentifier);
        }
        const response = await fetch(`${BaseURL}/monitoring/overview?${params.toString()}`);
        if (!response.ok) {
          throw new Error('Failed to load monitoring overview');
        }
        const data = await response.json();
        if (!isMounted) {
          return;
        }
        setOverview(data);
        setError(null);
        if (!selectedRunIdentifier && data.selected_run_identifier) {
          setSelectedRunIdentifier(data.selected_run_identifier);
        }
      } catch (fetchError) {
        if (isMounted) {
          setError(fetchError.message);
        }
      }
    };

    const unsubscribePoll = subscribeToSharedPoll(
      'monitoring-overview',
      3000,
      loadOverview,
      { runImmediately: true },
    );
    const unsubscribeSnapshot = subscribeToOperationsEvent('snapshot', loadOverview);
    const unsubscribeRuns = subscribeToOperationsEvent('runs.updated', loadOverview);
    const unsubscribeIncidents = subscribeToOperationsEvent('incidents.updated', loadOverview);
    const unsubscribeAnomalies = subscribeToOperationsEvent('anomalies.updated', loadOverview);

    return () => {
      isMounted = false;
      unsubscribePoll();
      unsubscribeSnapshot();
      unsubscribeRuns();
      unsubscribeIncidents();
      unsubscribeAnomalies();
    };
  }, [pollingEnabled, refreshTick, selectedRunIdentifier]);

  const runs = overview?.runs || [];
  const resources = overview?.resources;
  const dependencyStatus = Object.entries(resources?.dependency_status || {});
  const moduleMetrics = Object.entries(resources?.module_metrics || {}).filter(
    ([name]) => ['INGESTOR', 'ANOMALY'].includes(name),
  );
  const modelHealth = Object.entries(resources?.model_health || {}).filter(
    ([modelKey, health]) => mountedModelKeys.has(modelKey) && Boolean(health?.healthy),
  );
  const sources = overview?.sources || [];
  const modelBindings = overview?.model_bindings || [];
  const modelRegistrations = overview?.model_registrations || [];
  const triggers = overview?.latest_incidents || [];
  const anomalies = overview?.latest_anomalies || [];
  const recentEvents = overview?.recent_events || [];
  const feedEndpoints = overview?.feed_endpoints || [];
  const modelDisplayNames = modelRegistrations.reduce((result, registration) => {
    result[registration.model_key] = registration.display_name || registration.model_key;
    return result;
  }, {});
  const defaultModelKeysByStage = modelBindings.reduce((result, binding) => {
    if (binding.binding_scope === 'default' && binding.model_key) {
      result[binding.stage] = binding.model_key;
    }
    return result;
  }, {});
  const getDisplayNameForModelKey = (modelKey, fallbackLabel = 'Unconfigured') => {
    if (!modelKey) {
      return fallbackLabel;
    }
    return modelDisplayNames[modelKey] || modelKey;
  };
  const describeEffectiveBinding = (stage, explicitModelKey) => {
    const effectiveKey = explicitModelKey || defaultModelKeysByStage[stage] || null;
    return getDisplayNameForModelKey(effectiveKey, `No ${STAGE_LABELS[stage] || stage}`);
  };
  const formatStageLabel = (stage) => STAGE_LABELS[stage] || stage;
  const updateSourceEnabledState = async (sourceId, enabled) => {
    const nextSources = sources.map((source) => (
      source.id === sourceId
        ? { ...source, enabled }
        : source
    ));
    const source = sources.find((item) => item.id === sourceId);
    if (!source) {
      return;
    }
    setBusySourceId(sourceId);
    try {
      const saveResponse = await fetch(`${BaseURL}/sources`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(sanitizeSourcesForApi(nextSources)),
      });
      const saveData = await saveResponse.json().catch(() => ({}));
      if (!saveResponse.ok) {
        throw new Error(saveData.detail || 'Failed to update source state');
      }

      const remainingEnabledCount = nextSources.filter((item) => item.enabled).length;
      if (overview?.current_run_id) {
        const stopResponse = await fetch(`${BaseURL}/stop`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
        });
        const stopData = await stopResponse.json().catch(() => ({}));
        if (!stopResponse.ok) {
          throw new Error(stopData.detail || 'Failed to restart run');
        }
        if (remainingEnabledCount > 0) {
          const restartResponse = await fetch(`${BaseURL}/start`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
          });
          const restartData = await restartResponse.json().catch(() => ({}));
          if (!restartResponse.ok) {
            throw new Error(restartData.detail || 'Failed to restart run');
          }
          setBanner({ kind: 'success', text: `${source.label} updated. The run restarted with the new source set.` });
        } else {
          setBanner({ kind: 'success', text: `${source.label} stopped. No active sources remain, so the run was stopped.` });
        }
      } else if (enabled) {
        const startResponse = await fetch(`${BaseURL}/start`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
        });
        const startData = await startResponse.json().catch(() => ({}));
        if (!startResponse.ok) {
          throw new Error(startData.detail || 'Failed to start run');
        }
        setBanner({ kind: 'success', text: `${source.label} is starting.` });
      } else if (!enabled) {
        setBanner({ kind: 'success', text: `${source.label} stopped.` });
      } else {
        setBanner({ kind: 'success', text: `${source.label} is enabled for the next run.` });
      }
      setRefreshTick((value) => value + 1);
    } catch (actionError) {
      setBanner({ kind: 'error', text: actionError.message });
    } finally {
      setBusySourceId(null);
    }
  };

  const content = (
    <div className={embedded ? 'monitor-shell monitor-shell-embedded' : 'monitor-shell'}>
      <div className="monitor-header">
        <div>
          <h2>Monitor Run</h2>
          <p className="monitor-subtitle">
            Observe live orchestration state and publish stable feed endpoints for downstream systems.
          </p>
        </div>
        <div className="monitor-run-picker">
          <label htmlFor="monitor-run-select">Run</label>
          <select
            id="monitor-run-select"
            value={selectedRunIdentifier}
            onChange={(event) => setSelectedRunIdentifier(event.target.value)}
          >
            {runs.length === 0 && (
              <option value="">No runs</option>
            )}
            {runs.map((run) => (
              <option key={run.run_identifier} value={run.run_identifier}>
                {run.run_identifier}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <div className="monitor-alert monitor-alert-error">{error}</div>
      )}
      {banner && (
        <div className={`monitor-alert monitor-alert-${banner.kind === 'error' ? 'error' : 'info'}`}>{banner.text}</div>
      )}

      <div className="monitor-summary-grid">
        <div className="monitor-summary-card">
          <span className="monitor-label">System Status</span>
          <strong>{overview?.system_status || 'loading'}</strong>
          <span className="monitor-muted">
            {overview?.current_run_id ? `Current run ${overview.current_run_id}` : 'No active run'}
          </span>
        </div>
        <div className="monitor-summary-card">
          <span className="monitor-label">Selected Run</span>
          <strong>{overview?.selected_run_identifier || 'n/a'}</strong>
          <span className="monitor-muted">
            Admission {overview?.admission?.allowed ? 'open' : 'blocked'}
          </span>
        </div>
        <div className="monitor-summary-card">
          <span className="monitor-label">Resources</span>
          <strong>CPU {formatPercent(resources?.cpu_percent)}</strong>
          <span className="monitor-muted">
            Memory {formatPercent(resources?.memory_percent)} · Disk {formatPercent(resources?.disk_percent)}
          </span>
        </div>
        <div className="monitor-summary-card">
          <span className="monitor-label">Consumers</span>
          <strong>{feedEndpoints.length} endpoints</strong>
          <span className="monitor-muted">JSON feeds for triggers, model results, and orchestration data</span>
        </div>
        <div className="monitor-summary-card">
          <span className="monitor-label">Model Registry</span>
          <strong>{modelRegistrations.length} models</strong>
          <span className="monitor-muted">Detector, tracker, heuristic filter, and anomaly detection</span>
        </div>
      </div>

      <div className="monitor-grid">
        <div className="monitor-panel monitor-panel-wide">
          <div className="monitor-panel-header">
            <div>
              <h3>Feed Endpoints</h3>
              <p>Stable endpoints for other systems to poll.</p>
            </div>
          </div>
          <div className="monitor-endpoint-list">
            {feedEndpoints.map((endpoint) => (
              <div key={endpoint.path} className="monitor-endpoint-row">
                <div>
                  <strong>{endpoint.name}</strong>
                  <div className="monitor-muted">{endpoint.description}</div>
                </div>
                <code>{endpointURL(endpoint.path)}</code>
              </div>
            ))}
          </div>
        </div>

        <div className="monitor-panel">
          <div className="monitor-panel-header">
            <div>
              <h3>Runs</h3>
              <p>Recent run inventory and output volume.</p>
            </div>
          </div>
          <div className="monitor-table">
            <div className="monitor-table-head">
              <span>Run</span>
              <span>Status</span>
              <span>Outputs</span>
            </div>
            {runs.map((run) => (
              <div key={run.run_identifier} className="monitor-table-row">
                <span>{run.run_identifier}</span>
                <span>{run.status}</span>
                <span>{run.incident_count} triggers</span>
              </div>
            ))}
          </div>
        </div>

        <div className="monitor-panel">
          <div className="monitor-panel-header">
            <div>
              <h3>Dependencies</h3>
              <p>Shared service health for the control plane.</p>
            </div>
          </div>
          <div className="monitor-stack">
            {dependencyStatus.length === 0 && (
              <div className="monitor-empty">No dependency health available.</div>
            )}
            {dependencyStatus.map(([name, dependency]) => (
              <div key={name} className="monitor-data-row">
                <div>
                  <strong>{name}</strong>
                  <div className="monitor-muted">{dependency.detail || 'healthy'}</div>
                </div>
                <div className="monitor-data-meta">
                  <span className={`monitor-pill monitor-pill-${dependency.status === 'ok' ? 'running' : 'error'}`}>
                    {dependency.status}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="monitor-panel">
          <div className="monitor-panel-header">
            <div>
              <h3>Model Health</h3>
              <p>Registered model availability and readiness.</p>
            </div>
          </div>
          <div className="monitor-stack">
            {modelHealth.length === 0 && (
              <div className="monitor-empty">No model health available.</div>
            )}
            {modelHealth.map(([modelKey, health]) => (
              <div key={modelKey} className="monitor-data-row">
                <div>
                  <strong>{getDisplayNameForModelKey(modelKey, modelKey)}</strong>
                  <div className="monitor-muted">{formatStageLabel(health.stage)} · {health.adapter}</div>
                  <div className="monitor-muted">{health.detail || 'healthy'}</div>
                </div>
                <div className="monitor-data-meta">
                  <span className={`monitor-pill monitor-pill-${health.healthy ? 'running' : 'error'}`}>
                    {health.healthy ? 'healthy' : 'unhealthy'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="monitor-panel">
          <div className="monitor-panel-header">
            <div>
              <h3>Model Bindings</h3>
              <p>Resolved defaults and source-specific overrides.</p>
            </div>
          </div>
          <div className="monitor-stack">
            {modelBindings.length === 0 && (
              <div className="monitor-empty">No model bindings configured.</div>
            )}
            {modelBindings.map((binding) => (
              <div
                key={`${binding.binding_scope}-${binding.stage}-${binding.source_id || 'default'}`}
                className="monitor-data-row"
              >
                <div>
                  <strong>{formatStageLabel(binding.stage)}</strong>
                  <div className="monitor-muted">
                    {binding.binding_scope === 'default'
                      ? 'Default binding'
                      : `Source ${binding.source_id}`}
                  </div>
                </div>
                <div className="monitor-data-meta">
                  <span>{getDisplayNameForModelKey(binding.model_key, 'None')}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="monitor-panel">
          <div className="monitor-panel-header">
            <div>
              <h3>Module Backpressure</h3>
              <p>Queue-depth snapshots across the active AI pipeline.</p>
            </div>
          </div>
          <div className="monitor-stack">
            {moduleMetrics.length === 0 && (
              <div className="monitor-empty">No module queue telemetry available.</div>
            )}
            {moduleMetrics.map(([name, metrics]) => (
              <div key={name} className="monitor-data-row">
                <div>
                  <strong>{name}</strong>
                  <div className="monitor-muted">
                    {metrics.hottest_queue
                      ? `${metrics.hottest_queue} at depth ${metrics.max_queue_depth}`
                      : 'No queue pressure'}
                  </div>
                </div>
                <div className="monitor-data-meta">
                  <span className={`monitor-pill monitor-pill-${metrics.state === 'ok' ? 'running' : metrics.state}`}>
                    {metrics.state}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="monitor-panel">
          <div className="monitor-panel-header">
            <div>
              <h3>Sources</h3>
              <p>Current source queue and runtime state.</p>
            </div>
          </div>
          <div className="monitor-stack">
            {sources.length === 0 && (
              <div className="monitor-empty">No configured sources.</div>
            )}
            {sources.map((source) => (
              <div key={source.id || source.label} className="monitor-source-row">
                <div>
                  <strong>{source.label}</strong>
                  <div className="monitor-muted">{normalizeSourceKindLabel(source.kind)} · {describeFrameProcessing(source)}</div>
                  <div className="monitor-muted">
                    {describeEffectiveBinding('detector', source.detector_model_key)} · {describeEffectiveBinding('tracker', source.tracker_model_key)} · {describeEffectiveBinding('anomaly_stage_1', source.anomaly_stage_1_model_key)} · {describeEffectiveBinding('anomaly_stage_2', source.anomaly_stage_2_model_key)}
                  </div>
                  {(source.capture_fps || source.processed_fps) && (
                    <div className="monitor-muted">
                      Capture {source.capture_fps || 'n/a'} FPS · Processed {source.processed_fps || 'n/a'} FPS · Skipped {source.skipped_frames || 0}
                    </div>
                  )}
                </div>
                <div className="monitor-source-meta">
                  <span className={`monitor-pill monitor-pill-${source.state}`}>{source.state}</span>
                  <button
                    type="button"
                    className={source.enabled ? 'stop-button' : 'start-button'}
                    disabled={busySourceId === source.id}
                    onClick={() => updateSourceEnabledState(source.id, !source.enabled)}
                  >
                    {busySourceId === source.id
                      ? (source.enabled ? 'Stopping...' : 'Starting...')
                      : (source.enabled ? 'Stop Source' : 'Start Source')}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="monitor-panel">
          <div className="monitor-panel-header">
            <div>
              <h3>Triggers</h3>
              <p>Latest trigger output for the selected run.</p>
            </div>
          </div>
          <div className="monitor-stack">
            {triggers.length === 0 && (
              <div className="monitor-empty">No triggers available.</div>
            )}
            {triggers.map((incident) => (
                <div key={incident.incident_id} className="monitor-data-row">
                  <div>
                    <strong>{incident.display_title || incident.incident_type}</strong>
                    <div className="monitor-muted">{incident.incident_id}</div>
                  </div>
                  <div className="monitor-data-meta">
                    {incident.alert_level && <span>{incident.alert_level}</span>}
                    <span>{incident.status}</span>
                    <span>{formatDateTime(incident.incident_time)}</span>
                  </div>
                </div>
            ))}
          </div>
        </div>

        <div className="monitor-panel">
          <div className="monitor-panel-header">
            <div>
              <h3>Anomalies</h3>
              <p>Latest anomaly events emitted by the sidecar.</p>
            </div>
          </div>
          <div className="monitor-stack">
            {anomalies.length === 0 && (
              <div className="monitor-empty">No anomaly events available.</div>
            )}
            {anomalies.map((anomaly) => (
              <div key={anomaly.event_id} className="monitor-data-row">
                <div>
                  <strong>{anomaly.category}</strong>
                  <div className="monitor-muted">
                    {getDisplayNameForModelKey(anomaly.model_key, anomaly.model_key)}
                    {anomaly.stage_1_model_key || anomaly.stage_2_model_key
                      ? ` (S1 ${getDisplayNameForModelKey(anomaly.stage_1_model_key, 'n/a')} · S2 ${getDisplayNameForModelKey(anomaly.stage_2_model_key, 'n/a')})`
                      : ''}
                  </div>
                  <div className="monitor-muted">{anomaly.reasoning || 'No reasoning provided'}</div>
                </div>
                <div className="monitor-data-meta">
                  <span>{anomaly.score.toFixed(2)}</span>
                  <span>{anomaly.frame_id !== null ? `Frame ${anomaly.frame_id}` : 'Frame n/a'}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="monitor-panel">
          <div className="monitor-panel-header">
            <div>
              <h3>Resource Events</h3>
              <p>Recent orchestration and admission activity.</p>
            </div>
          </div>
          <div className="monitor-stack">
            {recentEvents.length === 0 && (
              <div className="monitor-empty">No resource events recorded yet.</div>
            )}
            {recentEvents.map((event) => (
              <div key={`${event.created_at}-${event.event_type}`} className="monitor-event-row">
                <div>
                  <strong>{event.event_type}</strong>
                  <div className="monitor-muted">{event.message}</div>
                </div>
                <div className="monitor-data-meta">
                  <span>{event.severity}</span>
                  <span>{formatDateTime(event.created_at)}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );

  if (embedded) {
    return <section className="monitor-page">{content}</section>;
  }

  return (
    <section className="monitor-page">
      {content}
    </section>
  );
};

export default MonitoringSection;
