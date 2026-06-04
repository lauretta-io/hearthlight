import React, { useEffect, useRef, useState } from 'react';
import { BaseURL } from '../config';
import { fetchJson, formatApiError } from '../utils/api';
import { formatDateTime } from '../utils/time';
import {
  formatSourceFrameProgress,
  getLiveRunHeadline,
  isRunActiveStatus as isRunLifecycleActive,
  resolveDisplaySystemStatus,
} from '../utils/runActivity';
import {
  RUN_STARTED_EVENT,
  SOURCES_UPDATED_EVENT,
  applyOptimisticRunOverview,
  dispatchRunStarted,
} from '../utils/runLifecycle';
import { subscribeToOperationsEvent } from '../utils/sharedEvents';
import { subscribeToSharedPoll } from '../utils/sharedPolling';
import '../styles/MonitoringPage.css';

const EMBEDDED_OVERVIEW_POLL_MS = 3000;
const STANDALONE_OVERVIEW_POLL_MS = 5000;
const RUN_STATUS_BURST_POLL_MS = 1000;
const RUN_STATUS_BURST_DURATION_MS = 60000;

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
const isSystemRunActive = (overview) => (
  isRunLifecycleActive(
    overview?.system_status,
    overview?.current_run_id,
    overview?.resources?.module_status,
  )
);

const canStopRun = (overview) => (
  ['running', 'initializing', 'stopping'].includes(overview?.system_status)
  && Boolean(overview?.current_run_id)
);

const getPreviewUrl = (source) => (
  source?.id ? `${BaseURL}/sources/${source.id}/preview.mjpeg` : null
);

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
  const [burstDeadline, setBurstDeadline] = useState(0);
  const loadOverviewRef = useRef(null);
  const transientBannerTimeoutRef = useRef(null);

  const showTransientBanner = (text, kind = 'info', durationMs = 4500) => {
    if (transientBannerTimeoutRef.current) {
      window.clearTimeout(transientBannerTimeoutRef.current);
    }
    setBanner({ kind, text });
    transientBannerTimeoutRef.current = window.setTimeout(() => {
      setBanner((current) => (current?.text === text ? null : current));
      transientBannerTimeoutRef.current = null;
    }, durationMs);
  };

  useEffect(() => () => {
    if (transientBannerTimeoutRef.current) {
      window.clearTimeout(transientBannerTimeoutRef.current);
    }
  }, []);

  useEffect(() => {
    if (!overview || banner?.kind === 'error') {
      return;
    }
    const steadyState = overview.system_status === 'running'
      || (overview.sources || []).some((source) => source.state === 'running');
    if (steadyState && banner?.text && /starting/i.test(banner.text)) {
      setBanner(null);
    }
  }, [overview, banner]);

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
    const refreshFromSettings = () => {
      setRefreshTick((value) => value + 1);
      loadOverviewRef.current?.();
    };
    const refreshFromRunStart = (event) => {
      const runId = event?.detail?.run_id ?? null;
      setBurstDeadline(Date.now() + RUN_STATUS_BURST_DURATION_MS);
      setOverview((previous) => applyOptimisticRunOverview(previous, runId));
      setRefreshTick((value) => value + 1);
      loadOverviewRef.current?.();
    };
    window.addEventListener(SOURCES_UPDATED_EVENT, refreshFromSettings);
    window.addEventListener(RUN_STARTED_EVENT, refreshFromRunStart);
    return () => {
      window.removeEventListener(SOURCES_UPDATED_EVENT, refreshFromSettings);
      window.removeEventListener(RUN_STARTED_EVENT, refreshFromRunStart);
    };
  }, []);

  useEffect(() => {
    if (!pollingEnabled || burstDeadline <= Date.now()) {
      return undefined;
    }
    const tick = () => {
      loadOverviewRef.current?.();
    };
    tick();
    const intervalId = window.setInterval(tick, RUN_STATUS_BURST_POLL_MS);
    const timeoutId = window.setTimeout(() => {
      setBurstDeadline(0);
    }, burstDeadline - Date.now());
    return () => {
      window.clearInterval(intervalId);
      window.clearTimeout(timeoutId);
    };
  }, [burstDeadline, pollingEnabled]);

  useEffect(() => {
    if (!pollingEnabled) {
      return undefined;
    }

    let isMounted = true;
    let inFlight = false;
    let abortController = null;
    const overviewPollMs = embedded ? EMBEDDED_OVERVIEW_POLL_MS : STANDALONE_OVERVIEW_POLL_MS;

    const loadOverview = async () => {
      if (inFlight) {
        return;
      }
      if (abortController) {
        abortController.abort();
      }
      abortController = new AbortController();
      inFlight = true;
      try {
        const params = new URLSearchParams({ limit: '8' });
        if (selectedRunIdentifier) {
          params.set('run_identifier', selectedRunIdentifier);
        }
        const response = await fetch(
          `${BaseURL}/monitoring/overview?${params.toString()}`,
          { signal: abortController.signal },
        );
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
        if (!isMounted || fetchError.name === 'AbortError') {
          return;
        }
        setError(fetchError.message);
      } finally {
        inFlight = false;
      }
    };

    loadOverviewRef.current = loadOverview;

    const unsubscribePoll = subscribeToSharedPoll(
      'monitoring-overview',
      overviewPollMs,
      loadOverview,
      { runImmediately: true },
    );
    const unsubscribeSnapshot = subscribeToOperationsEvent('snapshot', loadOverview);
    const unsubscribeRuns = subscribeToOperationsEvent('runs.updated', loadOverview);
    const unsubscribeIncidents = subscribeToOperationsEvent('incidents.updated', loadOverview);
    const unsubscribeAnomalies = subscribeToOperationsEvent('anomalies.updated', loadOverview);

    return () => {
      isMounted = false;
      loadOverviewRef.current = null;
      if (abortController) {
        abortController.abort();
      }
      unsubscribePoll();
      unsubscribeSnapshot();
      unsubscribeRuns();
      unsubscribeIncidents();
      unsubscribeAnomalies();
    };
  }, [pollingEnabled, refreshTick, selectedRunIdentifier, embedded]);

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
  const handleSourceRunAction = async (source) => {
    const runIsActive = isSystemRunActive(overview);
    if (runIsActive && source.enabled) {
      await updateSourceEnabledState(source.id, false);
      return;
    }
    setBusySourceId(source.id);
    try {
      const nextSources = sources.map((item) => (
        item.id === source.id ? { ...item, enabled: true } : item
      ));
      await fetchJson(
        `${BaseURL}/settings/input-sources`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(sanitizeSourcesForApi(nextSources)),
        },
        'Failed to update source state',
        60000,
      );
      const startPayload = await fetchJson(
        `${BaseURL}/start`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' } },
        'Failed to start run',
        120000,
      );
      setOverview((previous) => applyOptimisticRunOverview(previous, startPayload?.run_id));
      dispatchRunStarted(startPayload?.run_id);
      showTransientBanner(`${source.label} run is starting. Status updates within a few seconds.`);
      setRefreshTick((value) => value + 1);
    } catch (actionError) {
      setBanner({ kind: 'error', text: formatApiError(actionError, 'Failed to start run.') });
    } finally {
      setBusySourceId(null);
    }
  };
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
      await fetchJson(
        `${BaseURL}/settings/input-sources`,
        {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(sanitizeSourcesForApi(nextSources)),
        },
        'Failed to update source state',
        60000,
      );

  const remainingEnabledCount = nextSources.filter((item) => item.enabled).length;
  if (canStopRun(overview)) {
        await fetchJson(
          `${BaseURL}/stop`,
          { method: 'POST', headers: { 'Content-Type': 'application/json' } },
          'Failed to stop run',
          60000,
        );
        if (remainingEnabledCount > 0) {
          const startPayload = await fetchJson(
            `${BaseURL}/start`,
            { method: 'POST', headers: { 'Content-Type': 'application/json' } },
            'Failed to restart run',
            120000,
          );
          setOverview((previous) => applyOptimisticRunOverview(previous, startPayload?.run_id));
          dispatchRunStarted(startPayload?.run_id);
          showTransientBanner(`${source.label} updated. The run restarted with the new source set.`);
        } else {
          setBanner({ kind: 'success', text: `${source.label} stopped. No active sources remain, so the run was stopped.` });
        }
      } else if (enabled) {
        const startPayload = await fetchJson(
          `${BaseURL}/start`,
          { method: 'POST', headers: { 'Content-Type': 'application/json' } },
          'Failed to start run',
          120000,
        );
        setOverview((previous) => applyOptimisticRunOverview(previous, startPayload?.run_id));
        dispatchRunStarted(startPayload?.run_id);
        showTransientBanner(`${source.label} is starting. Status updates within a few seconds.`);
      } else if (!enabled) {
        setBanner({ kind: 'success', text: `${source.label} stopped.` });
      } else {
        setBanner({ kind: 'success', text: `${source.label} is enabled for the next run.` });
      }
      setRefreshTick((value) => value + 1);
    } catch (actionError) {
      setBanner({ kind: 'error', text: formatApiError(actionError, 'Failed to update source or start run.') });
    } finally {
      setBusySourceId(null);
    }
  };

  const displaySystemStatus = resolveDisplaySystemStatus(overview);
  const runHeadline = getLiveRunHeadline(
    displaySystemStatus,
    overview?.current_run_id,
    overview?.resources?.module_status,
  );
  const runIsActive = isSystemRunActive(overview);

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
      {runHeadline && !banner && (
        <div className="monitor-run-headline">{runHeadline}</div>
      )}

      <div className="monitor-summary-grid">
        <div className="monitor-summary-card">
          <span className="monitor-label">System Status</span>
          <strong className={`monitor-status-value monitor-status-${displaySystemStatus || 'loading'}`}>
            {displaySystemStatus || 'loading'}
          </strong>
          <span className="monitor-muted">
            {overview?.current_run_id
              ? `Current run ${overview.current_run_id}`
              : (displaySystemStatus === 'running'
                ? 'Workers active — syncing run metadata'
                : 'No active run')}
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
            {sources.map((source) => {
              const frameProgressText = formatSourceFrameProgress(source, { runActive: runIsActive });
              const previewUrl = source.enabled && (
                source.kind === 'video_upload'
                || (!runIsActive && source.kind !== 'video_upload')
              )
                ? getPreviewUrl(source)
                : null;
              const showStop = runIsActive && source.enabled;
              return (
                <article key={source.id || source.label} className="monitor-source-card">
                  {previewUrl && (
                    <div className="monitor-source-card__preview">
                      <img
                        className="monitor-source-card__preview-media"
                        src={previewUrl}
                        alt={`${source.label} preview`}
                      />
                    </div>
                  )}
                  <div className="monitor-source-card__header">
                    <div className="monitor-source-card__title">
                      <h4>{source.label}</h4>
                      <p className="monitor-muted">
                        {normalizeSourceKindLabel(source.kind)} · {describeFrameProcessing(source)}
                      </p>
                    </div>
                    <span className={`monitor-pill monitor-pill-${source.state}`}>{source.state}</span>
                  </div>
                  <ul className="monitor-source-card__bindings">
                    <li>{describeEffectiveBinding('detector', source.detector_model_key)}</li>
                    <li>{describeEffectiveBinding('tracker', source.tracker_model_key)}</li>
                    <li>{describeEffectiveBinding('anomaly_stage_1', source.anomaly_stage_1_model_key)}</li>
                    <li>{describeEffectiveBinding('anomaly_stage_2', source.anomaly_stage_2_model_key)}</li>
                  </ul>
                  {frameProgressText && (
                    <div className="monitor-source-card__frames">{frameProgressText}</div>
                  )}
                  {(source.capture_fps || source.processed_fps) && (
                    <p className="monitor-muted monitor-source-card__metrics">
                      Capture {source.capture_fps || 'n/a'} FPS · Processed {source.processed_fps || 'n/a'} FPS · Skipped {source.skipped_frames || 0}
                    </p>
                  )}
                  <div className="monitor-source-card__actions">
                    <button
                      type="button"
                      className={showStop ? 'stop-button' : 'start-button'}
                      disabled={busySourceId === source.id}
                      onClick={() => (
                        showStop
                          ? updateSourceEnabledState(source.id, false)
                          : handleSourceRunAction(source)
                      )}
                    >
                      {busySourceId === source.id || source.state === 'initializing'
                        ? (showStop ? 'Stopping...' : 'Starting run...')
                        : (showStop ? 'Stop Source' : 'Start Run')}
                    </button>
                  </div>
                </article>
              );
            })}
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
