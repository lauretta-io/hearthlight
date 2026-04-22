import React, { useEffect, useRef, useState } from 'react';
import '../styles/EntityPage.css';
import EntityCard from './EntityCard';
import ErrorAlert from './ErrorAlert';
import LoadingAlert from './LoadingAlert';
import { BaseURL } from '../config';

const FALLBACK_REFRESH_INTERVAL_MS = 15000;

const EntityPage = () => {
  const [entities, setEntities] = useState([]);
  const [runIdentifiers, setRunIdentifiers] = useState([]);
  const [selectedRunIdentifier, setSelectedRunIdentifier] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingRuns, setIsLoadingRuns] = useState(true);
  const [error, setError] = useState(null);
  const [refreshWarning, setRefreshWarning] = useState(null);
  const followLatestRunRef = useRef(true);
  const selectedRunIdentifierRef = useRef('');
  const fetchRunIdentifiersRef = useRef(async () => {});
  const fetchEntitiesRef = useRef(async () => {});

  selectedRunIdentifierRef.current = selectedRunIdentifier;

  fetchRunIdentifiersRef.current = async () => {
    try {
      const response = await fetch(`${BaseURL}/genetec/runs`);
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
      setRefreshWarning(null);
      setError(null);
    } catch (fetchError) {
      if (runIdentifiers.length === 0) {
        setError(fetchError.message);
      } else {
        setRefreshWarning('Entity updates are temporarily unavailable. Showing the last successful results.');
      }
    } finally {
      setIsLoadingRuns(false);
      setIsLoading(false);
    }
  };

  fetchEntitiesRef.current = async (runIdentifier = selectedRunIdentifierRef.current) => {
    if (!runIdentifier) {
      setEntities([]);
      setIsLoading(false);
      return;
    }

    try {
      const response = await fetch(`${BaseURL}/genetec/entities/?run_identifier=${runIdentifier}&include_crop=true`);
      if (!response.ok) {
        throw new Error('Failed to fetch entities; is the backend running?');
      }
      const data = await response.json();
      setEntities(data);
      setRefreshWarning(null);
      setError(null);
    } catch (fetchError) {
      if (entities.length === 0) {
        setError(fetchError.message);
      } else {
        setRefreshWarning('Entity updates are temporarily unavailable. Showing the last successful results.');
      }
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
    fetchEntitiesRef.current(selectedRunIdentifier);
    const intervalId = setInterval(
      () => fetchEntitiesRef.current(selectedRunIdentifier),
      FALLBACK_REFRESH_INTERVAL_MS,
    );
    return () => clearInterval(intervalId);
  }, [selectedRunIdentifier]);

  useEffect(() => {
    if (typeof EventSource === 'undefined') {
      return undefined;
    }

    const eventSource = new EventSource(`${BaseURL}/genetec/events`);

    const refreshRuns = () => {
      fetchRunIdentifiersRef.current();
    };
    const refreshEntities = () => {
      fetchEntitiesRef.current();
    };
    const refreshAll = () => {
      refreshRuns();
      refreshEntities();
    };

    eventSource.addEventListener('snapshot', refreshAll);
    eventSource.addEventListener('runs.updated', refreshRuns);
    eventSource.addEventListener('entities.updated', refreshEntities);
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
    <div className="entity-page-container">
      <div className="section-header">
        <h2>Current Entities</h2>
        
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

      {refreshWarning ? <ErrorAlert message={refreshWarning} /> : null}
      
      {runIdentifiers.length === 0 ? (
        <div className="empty-state">
          No runs in database
        </div>
      ) : isLoading ? (
        <LoadingAlert message="Loading entities..." />
      ) : entities.length === 0 ? (
        <div className="empty-state">
          No entities found for this run.
        </div>
      ) : (
        <div className="entities-list">
          {entities.slice().reverse().map((entity) => (
            <EntityCard 
              key={entity.entity_id} 
              entity={entity} 
              includeResolve={true}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default EntityPage;