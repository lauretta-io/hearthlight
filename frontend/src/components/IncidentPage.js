import React, { useEffect, useRef, useState } from 'react';
import '../styles/IncidentPage.css';
import IncidentCard from './IncidentCard';
import ErrorAlert from './ErrorAlert';
import LoadingAlert from './LoadingAlert';
import { BaseURL } from '../config';

const FALLBACK_REFRESH_INTERVAL_MS = 15000;

const IncidentPage = () => {
  const [incidents, setIncidents] = useState([]);
  const [anomalies, setAnomalies] = useState([]);
  const [runIdentifiers, setRunIdentifiers] = useState([]);
  const [selectedRunIdentifier, setSelectedRunIdentifier] = useState('');
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
    if (!runIdentifier) {
      setIncidents([]);
      setAnomalies([]);
      setIsLoading(false);
      return;
    }

    try {
      const [incidentResponse, feedResponse] = await Promise.all([
        fetch(
          `${BaseURL}/operations/incidents/?run_identifier=${runIdentifier}&include_crop=true`,
        ),
        fetch(`${BaseURL}/feeds/algorithm?run_identifier=${runIdentifier}&limit=50`),
      ]);

      if (!incidentResponse.ok) {
        throw new Error('Failed to fetch incidents; is the backend running?');
      }
      if (!feedResponse.ok) {
        throw new Error('Failed to fetch anomaly events; is the backend running?');
      }

      const [incidentData, feedData] = await Promise.all([
        incidentResponse.json(),
        feedResponse.json(),
      ]);
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
    fetchRunIdentifiersRef.current();
    const intervalId = setInterval(
      () => fetchRunIdentifiersRef.current(),
      FALLBACK_REFRESH_INTERVAL_MS,
    );
    return () => clearInterval(intervalId);
  }, []);

  useEffect(() => {
    fetchIncidentDataRef.current(selectedRunIdentifier);
    const intervalId = setInterval(
      () => fetchIncidentDataRef.current(selectedRunIdentifier),
      FALLBACK_REFRESH_INTERVAL_MS,
    );
    return () => clearInterval(intervalId);
  }, [selectedRunIdentifier]);

  useEffect(() => {
    setSelectedAnomaly(null);
  }, [selectedRunIdentifier]);

  useEffect(() => {
    if (typeof EventSource === 'undefined') {
      return undefined;
    }

    const eventSource = new EventSource(`${BaseURL}/operations/events`);

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

    eventSource.addEventListener('snapshot', refreshAll);
    eventSource.addEventListener('runs.updated', refreshRuns);
    eventSource.addEventListener('incidents.updated', refreshIncidentData);
    eventSource.addEventListener('anomalies.updated', refreshIncidentData);
    eventSource.onerror = () => {};

    return () => {
      eventSource.close();
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
        <h2>Current Incidents</h2>

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
      </div>

      {runIdentifiers.length === 0 ? (
        <div className="empty-state">
          No runs in database
        </div>
      ) : isLoading ? (
        <LoadingAlert message="Loading incidents..." />
      ) : incidents.length === 0 && anomalies.length === 0 ? (
        <div className="empty-state">
          No incidents or anomaly events found for this run.
        </div>
      ) : (
        <>
          <div className="incident-section">
            <div className="incident-section-header">
              <h3>Incident Records</h3>
              <span>{incidents.length}</span>
            </div>
            {incidents.length === 0 ? (
              <div className="empty-state compact-empty-state">
                No incident records found for this run.
              </div>
            ) : (
              <div className="incidents-list">
                {incidents.slice().reverse().map((incident) => (
                  <IncidentCard
                    key={incident.incident_id}
                    incident={incident}
                    includeResolve
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
                      <strong>{anomaly.category}</strong>
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
