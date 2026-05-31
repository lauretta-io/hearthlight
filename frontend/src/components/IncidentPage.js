import React, { useEffect, useRef, useState } from 'react';
import '../styles/IncidentPage.css';
import IncidentCard from './IncidentCard';
import ErrorAlert from './ErrorAlert';
import LoadingAlert from './LoadingAlert';
import { BaseURL } from '../config';
import { subscribeToOperationsEvent } from '../utils/sharedEvents';
import { subscribeToSharedPoll } from '../utils/sharedPolling';

const FALLBACK_REFRESH_INTERVAL_MS = 15000;
const ALERT_FILTER_OPTIONS = [
  { value: 'new_this_run', label: 'New This Run' },
  { value: 'all', label: 'All Alerts' },
];

const IncidentPage = () => {
  const [incidents, setIncidents] = useState([]);
  const [anomalies, setAnomalies] = useState([]);
  const [runIdentifiers, setRunIdentifiers] = useState([]);
  const [selectedRunIdentifier, setSelectedRunIdentifier] = useState('');
  const [alertFilterMode, setAlertFilterMode] = useState('new_this_run');
  const [selectedAnomaly, setSelectedAnomaly] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingRuns, setIsLoadingRuns] = useState(true);
  const [error, setError] = useState(null);
  const followLatestRunRef = useRef(true);
  const selectedRunIdentifierRef = useRef('');
  const fetchRunIdentifiersRef = useRef(async () => {});
  const fetchIncidentDataRef = useRef(async () => {});

  const getAnomalyVideoUrl = (anomaly) => {
    if (!anomaly || !selectedRunIdentifier) {
      return '';
    }
    const clipDuration = Number.isFinite(anomaly?.duration_seconds)
      ? anomaly.duration_seconds
      : 10;
    const params = new URLSearchParams({
      event_id: anomaly.event_id,
      run_identifier: selectedRunIdentifier,
      duration: String(clipDuration),
    });
    return `${BaseURL}/operations/anomaly_video/?${params.toString()}`;
  };

  const formatAnomalyTime = (timestamp) => {
    if (!timestamp) {
      return 'Time unavailable';
    }
    const parsed = new Date(timestamp);
    if (Number.isNaN(parsed.getTime())) {
      return timestamp;
    }
    return parsed.toLocaleString();
  };

  const formatAnomalyList = (values) => (
    Array.isArray(values) && values.length > 0 ? values.join(', ') : 'None reported'
  );

  const getAnomalyTitle = (anomaly) => anomaly?.title || anomaly?.category || 'Anomaly';

  selectedRunIdentifierRef.current = selectedRunIdentifier;

  fetchRunIdentifiersRef.current = async () => {
    try {
      const response = await fetch(`${BaseURL}/operations/runs`);
      if (!response.ok) {
        throw new Error('Failed to fetch run identifiers; is the backend running?');
      }
      const data = await response.json();
      setRunIdentifiers(data);

      const latestRunIdentifier = data.length > 0 ? data[data.length - 1] : '';
      setSelectedRunIdentifier((currentRunIdentifier) => {
        if (!latestRunIdentifier) {
          return '';
        }
        if (!currentRunIdentifier) {
          return latestRunIdentifier;
        }
        if (!data.includes(currentRunIdentifier)) {
          return latestRunIdentifier;
        }
        if (followLatestRunRef.current) {
          return latestRunIdentifier;
        }
        return currentRunIdentifier;
      });
      setError(null);
    } catch (fetchError) {
      setError(fetchError.message);
    } finally {
      setIsLoadingRuns(false);
      setIsLoading(false);
    }
  };

  fetchIncidentDataRef.current = async (
    runIdentifier = selectedRunIdentifierRef.current,
  ) => {
    if (!runIdentifier && alertFilterMode !== 'all') {
      setIncidents([]);
      setAnomalies([]);
      setIsLoading(false);
      return;
    }

    try {
      const incidentParams = new URLSearchParams({ include_crop: 'true', filter_mode: alertFilterMode });
      if (alertFilterMode !== 'all' && runIdentifier) {
        incidentParams.set('run_identifier', runIdentifier);
      }
      const requests = [fetch(`${BaseURL}/operations/incidents?${incidentParams.toString()}`)];
      if (runIdentifier) {
        requests.push(fetch(`${BaseURL}/feeds/algorithm?run_identifier=${runIdentifier}&limit=50`));
      }
      const [incidentResponse, feedResponse] = await Promise.all(requests);

      if (!incidentResponse.ok) {
        throw new Error('Failed to fetch triggers; is the backend running?');
      }
      if (feedResponse && !feedResponse.ok) {
        throw new Error('Failed to fetch anomaly events; is the backend running?');
      }

      const incidentData = await incidentResponse.json();
      const feedData = feedResponse ? await feedResponse.json() : { anomalies: [] };
      setIncidents(incidentData);
      setAnomalies(Array.isArray(feedData.anomalies) ? feedData.anomalies : []);
      setError(null);
    } catch (fetchError) {
      setError(fetchError.message);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    const unsubscribe = subscribeToSharedPoll(
      'incident-runs',
      FALLBACK_REFRESH_INTERVAL_MS,
      () => fetchRunIdentifiersRef.current(),
      { runImmediately: true },
    );
    return () => unsubscribe();
  }, []);

  useEffect(() => {
    const unsubscribe = subscribeToSharedPoll(
      'incident-data',
      FALLBACK_REFRESH_INTERVAL_MS,
      () => fetchIncidentDataRef.current(selectedRunIdentifier),
      { runImmediately: true },
    );
    return () => unsubscribe();
  }, [selectedRunIdentifier, alertFilterMode]);

  useEffect(() => {
    setSelectedAnomaly(null);
  }, [selectedRunIdentifier]);

  useEffect(() => {
    const refreshRuns = () => {
      fetchRunIdentifiersRef.current();
    };
    const refreshIncidentData = () => {
      fetchIncidentDataRef.current();
    };
    const refreshAll = () => {
      refreshRuns();
      refreshIncidentData();
    };

    const unsubscribeSnapshot = subscribeToOperationsEvent('snapshot', refreshAll);
    const unsubscribeRuns = subscribeToOperationsEvent('runs.updated', refreshRuns);
    const unsubscribeIncidents = subscribeToOperationsEvent('incidents.updated', refreshIncidentData);
    const unsubscribeAnomalies = subscribeToOperationsEvent('anomalies.updated', refreshIncidentData);

    return () => {
      unsubscribeSnapshot();
      unsubscribeRuns();
      unsubscribeIncidents();
      unsubscribeAnomalies();
    };
  }, []);

  const handleRunChange = (event) => {
    const nextRunIdentifier = event.target.value;
    const latestRunIdentifier =
      runIdentifiers.length > 0 ? runIdentifiers[runIdentifiers.length - 1] : '';
    followLatestRunRef.current = nextRunIdentifier === latestRunIdentifier;
    setSelectedRunIdentifier(nextRunIdentifier);
  };

  if (error) return <ErrorAlert message={error} />;
  if (isLoadingRuns) return <LoadingAlert message="Loading run identifiers..." />;

  return (
    <div className="incident-page-container">
      <div className="section-header">
        <h2>Current Triggers</h2>

        {runIdentifiers.length > 0 ? (
          <div className="run-selector">
            <label htmlFor="run-select">Select Run:</label>
            <select
              id="run-select"
              value={selectedRunIdentifier}
              onChange={handleRunChange}
            >
              {runIdentifiers.map((runId) => (
                <option key={runId} value={runId}>
                  {runId}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        <div className="run-selector">
          <label htmlFor="alert-filter-select">Alert View:</label>
          <select
            id="alert-filter-select"
            value={alertFilterMode}
            onChange={(event) => setAlertFilterMode(event.target.value)}
          >
            {ALERT_FILTER_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </div>
      </div>

      {runIdentifiers.length === 0 ? (
        <div className="empty-state">
          No runs in database
        </div>
      ) : isLoading ? (
        <LoadingAlert message="Loading triggers..." />
      ) : incidents.length === 0 && anomalies.length === 0 ? (
        <div className="empty-state">
          No triggers or anomaly events found for this run.
        </div>
      ) : (
        <>
          <div className="incident-section">
            <div className="incident-section-header">
              <h3>Trigger Records</h3>
              <span>{incidents.length}</span>
            </div>
            {incidents.length === 0 ? (
              <div className="empty-state compact-empty-state">
                {alertFilterMode === 'all'
                  ? 'No persisted alerts have been recorded yet.'
                  : 'No trigger records found for this run.'}
              </div>
            ) : (
              <div className="incidents-list">
                {incidents.map((incident) => (
                  <IncidentCard
                    key={incident.incident_id}
                    incident={incident}
                  />
                ))}
              </div>
            )}
          </div>

          <div className="incident-section">
            <div className="incident-section-header">
              <h3>Anomaly Events</h3>
              <span>{anomalies.length}</span>
            </div>
            {anomalies.length === 0 ? (
              <div className="empty-state compact-empty-state">
                No anomaly events found for this run.
              </div>
            ) : (
              <div className="incident-anomaly-list">
                {anomalies.map((anomaly) => (
                  <button
                    key={anomaly.event_id}
                    type="button"
                    className="incident-anomaly-card"
                    onClick={() => setSelectedAnomaly(anomaly)}
                  >
                    <div>
                      <strong>{getAnomalyTitle(anomaly)}</strong>
                      <div className="incident-anomaly-meta">
                        {formatAnomalyTime(anomaly.event_time)}
                        {' · '}
                        {anomaly.model_key}
                        {' · '}
                        {anomaly.frame_id !== null ? `Frame ${anomaly.frame_id}` : 'Frame n/a'}
                      </div>
                      <div className="incident-anomaly-reason">
                        {anomaly.reasoning || 'No reasoning provided'}
                      </div>
                    </div>
                    <div className="incident-anomaly-side">
                      <span>{anomaly.score.toFixed(2)}</span>
                      <span>View clip</span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>

          {selectedAnomaly ? (
            <div
              className="incident-modal-backdrop"
              onClick={() => setSelectedAnomaly(null)}
              role="presentation"
            >
              <div
                className="incident-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="incident-anomaly-modal-title"
                onClick={(event) => event.stopPropagation()}
              >
                <div className="incident-modal-header">
                  <div>
                    <h3 id="incident-anomaly-modal-title">{getAnomalyTitle(selectedAnomaly)}</h3>
                    <div className="incident-modal-subtitle">
                      {formatAnomalyTime(selectedAnomaly.event_time)}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="incident-modal-close"
                    onClick={() => setSelectedAnomaly(null)}
                    aria-label="Close anomaly details"
                  >
                    Close
                  </button>
                </div>
                <div className="incident-modal-video-shell">
                  <video
                    key={selectedAnomaly.event_id}
                    controls
                    autoPlay
                    playsInline
                    preload="auto"
                    className="incident-modal-video"
                    src={getAnomalyVideoUrl(selectedAnomaly)}
                    type="video/mp4"
                  >
                    Your browser does not support inline video playback.
                  </video>
                </div>
                <div className="incident-modal-body">
                  <div className="incident-modal-section">
                    <span className="incident-modal-label">Summary</span>
                    <p>{selectedAnomaly.reasoning || 'No reasoning provided'}</p>
                  </div>
                  <div className="incident-modal-section incident-modal-grid">
                    <div>
                      <span className="incident-modal-label">Visible Items</span>
                      <p>{formatAnomalyList(selectedAnomaly.visible_items)}</p>
                    </div>
                    <div>
                      <span className="incident-modal-label">Visible Activities</span>
                      <p>{formatAnomalyList(selectedAnomaly.visible_activities)}</p>
                    </div>
                  </div>
                  <div className="incident-modal-section incident-modal-grid">
                    <div>
                      <span className="incident-modal-label">Event ID</span>
                      <p>{selectedAnomaly.event_id}</p>
                    </div>
                    <div>
                      <span className="incident-modal-label">Score</span>
                      <p>{selectedAnomaly.score.toFixed(2)}</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
};

export default IncidentPage;
