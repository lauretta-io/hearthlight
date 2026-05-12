import React, { useEffect, useState } from 'react';
import { BaseURL } from '../config';
import { formatDateTime } from '../utils/time';
import '../styles/MonitoringPage.css';

const formatPercent = (value) => (
  value === null || value === undefined ? 'n/a' : `${value.toFixed(1)}%`
);

const endpointURL = (path) => `${BaseURL}${path}`;
const STAGE_LABELS = {
  detector: 'Detector',
  tracker: 'Tracker',
  anomaly_stage_1: 'Anomaly Stage 1',
  anomaly_stage_2: 'Anomaly Stage 2',
};

const MonitoringSection = ({ embedded = false, pollingEnabled = true }) => {
  const [overview, setOverview] = useState(null);
  const [selectedRunIdentifier, setSelectedRunIdentifier] = useState('');
  const [error, setError] = useState(null);

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

    loadOverview();
    const intervalId = window.setInterval(loadOverview, 3000);

    return () => {
      isMounted = false;
      window.clearInterval(intervalId);
    };
  }, [pollingEnabled, selectedRunIdentifier]);

  const runs = overview?.runs || [];
  const resources = overview?.resources;
  const dependencyStatus = Object.entries(resources?.dependency_status || {});
  const moduleMetrics = Object.entries(resources?.module_metrics || {});
  const modelHealth = Object.entries(resources?.model_health || {});
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

  const content = (
    <div className={embedded ? 'monitor-shell monitor-shell-embedded' : 'monitor-shell'}>
      <div className="monitor-header">
        <div>
          <h2>Monitoring</h2>
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
          <span className="monitor-muted">JSON feeds for triggers, entities, and orchestration data</span>
        </div>
        <div className="monitor-summary-card">
          <span className="monitor-label">Model Registry</span>
          <strong>{modelRegistrations.length} models</strong>
          <span className="monitor-muted">Detector, tracker, anomaly Stage 1, and anomaly Stage 2</span>
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
                  <div className="monitor-muted">{source.kind}</div>
                  <div className="monitor-muted">
                    {describeEffectiveBinding('detector', source.detector_model_key)} · {describeEffectiveBinding('tracker', source.tracker_model_key)} · {describeEffectiveBinding('anomaly_stage_1', source.anomaly_stage_1_model_key)} · {describeEffectiveBinding('anomaly_stage_2', source.anomaly_stage_2_model_key)}
                  </div>
                </div>
                <div className="monitor-source-meta">
                  <span className={`monitor-pill monitor-pill-${source.state}`}>{source.state}</span>
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
