import React, { useEffect, useMemo, useState } from 'react';
import { BaseURL } from '../config';
import { subscribeToOperationsEvent } from '../utils/sharedEvents';
import { subscribeToSharedPoll } from '../utils/sharedPolling';
import '../styles/CameraConfig.css';

const PAGE_SIZE = 20;
const REFRESH_INTERVAL_MS = 3000;
const STAGE_LABELS = {
  detector: 'Detector',
  tracker: 'Tracker',
  anomaly_stage_1: 'Heuristic Filter',
  anomaly_stage_2: 'Anomaly Detection',
};

const mergeLogRecords = (incomingRecords, existingRecords = []) => {
  const merged = [];
  const seen = new Set();
  [...incomingRecords, ...existingRecords].forEach((record) => {
    if (!record || seen.has(record.id)) {
      return;
    }
    seen.add(record.id);
    merged.push(record);
  });
  return merged;
};

const ModelLogsPage = () => {
  const [sources, setSources] = useState([]);
  const [loadedRecords, setLoadedRecords] = useState([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [total, setTotal] = useState(0);
  const [rateSummary, setRateSummary] = useState({});
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [expandedRowId, setExpandedRowId] = useState(null);
  const [error, setError] = useState(null);
  const [filters, setFilters] = useState({
    stage: '',
    source_id: '',
    result_query: '',
  });

  useEffect(() => {
    const loadSources = async () => {
      try {
        const response = await fetch(`${BaseURL}/sources`);
        if (!response.ok) {
          throw new Error('Failed to load sources');
        }
        const data = await response.json();
        setSources(Array.isArray(data) ? data : []);
      } catch (loadError) {
        console.error(loadError);
      }
    };
    loadSources();
  }, []);

  const queryString = useMemo(() => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(PAGE_SIZE),
    });
    return params.toString();
  }, [page]);

  const filteredRecords = useMemo(() => {
    const query = filters.result_query.trim().toLowerCase();
    return loadedRecords.filter((record) => {
      if (filters.stage && record.stage !== filters.stage) {
        return false;
      }
      if (filters.source_id && String(record.source_id) !== String(filters.source_id)) {
        return false;
      }
      if (!query) {
        return true;
      }
      const haystack = [
        record.source_label,
        record.model_display_name,
        record.model_key,
        record.result_summary,
        STAGE_LABELS[record.stage] || record.stage,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return haystack.includes(query);
    });
  }, [filters, loadedRecords]);

  useEffect(() => {
    let active = true;
    const loadLogs = async ({ refresh = false } = {}) => {
      if (refresh || page === 1) {
        setIsLoading(true);
      } else {
        setIsLoadingMore(true);
      }
      try {
        const response = await fetch(`${BaseURL}/model-logs?${queryString}`);
        if (!response.ok) {
          throw new Error('Failed to load model logs');
        }
        const data = await response.json();
        if (!active) {
          return;
        }
        setLoadedRecords((previous) => {
          const incomingRecords = Array.isArray(data.records) ? data.records : [];
          if (refresh || page === 1) {
            return mergeLogRecords(incomingRecords, previous);
          }
          return mergeLogRecords(previous, incomingRecords);
        });
        setHasMore(Boolean(data.has_more));
        setTotal(Number.isFinite(data.total) ? data.total : 0);
        if (refresh || page === 1) {
          setRateSummary(data.rate_summary || {});
        }
        setError(null);
      } catch (loadError) {
        if (active) {
          setError(loadError.message);
        }
      } finally {
        if (active) {
          setIsLoading(false);
          setIsLoadingMore(false);
        }
      }
    };
    const refreshLogs = () => loadLogs({ refresh: true });
    const unsubscribePoll = subscribeToSharedPoll(
      'model-logs',
      REFRESH_INTERVAL_MS,
      refreshLogs,
      { runImmediately: true },
    );
    const unsubscribeSnapshot = subscribeToOperationsEvent('snapshot', refreshLogs);
    const unsubscribeIncidents = subscribeToOperationsEvent('incidents.updated', refreshLogs);
    const unsubscribeAnomalies = subscribeToOperationsEvent('anomalies.updated', refreshLogs);
    const unsubscribeRuns = subscribeToOperationsEvent('runs.updated', refreshLogs);
    return () => {
      active = false;
      unsubscribePoll();
      unsubscribeSnapshot();
      unsubscribeIncidents();
      unsubscribeAnomalies();
      unsubscribeRuns();
    };
  }, [page, queryString]);

  const updateFilter = (field, value) => {
    setExpandedRowId(null);
    setFilters((previous) => ({
      ...previous,
      [field]: value,
    }));
  };

  return (
    <section className="settings-shell">
      <div className="settings-header">
        <div>
          <h2>Model Logs</h2>
          <p className="settings-subtitle">
            Review readable per-frame detector and anomaly results, newest first.
          </p>
        </div>
      </div>

      <section className="control-column model-log-column">
        <div className="model-log-meta-panel">
          <div className="model-log-filter-copy">
            <h3>Filters</h3>
            <p>Filter by model stage, camera, or result text.</p>
          </div>
          <div className="model-log-filter-row">
            <label className="model-log-filter-field">
              <span>Model Type</span>
              <select value={filters.stage} onChange={(event) => updateFilter('stage', event.target.value)}>
                <option value="">All model types</option>
                {Object.entries(STAGE_LABELS).map(([stage, label]) => (
                  <option key={stage} value={stage}>{label}</option>
                ))}
              </select>
            </label>
            <label className="model-log-filter-field">
              <span>Camera</span>
              <select value={filters.source_id} onChange={(event) => updateFilter('source_id', event.target.value)}>
                <option value="">All cameras</option>
                {sources.map((source) => (
                  <option key={source.id} value={source.id}>
                    {source.label || `Source ${source.id}`}
                  </option>
                ))}
              </select>
            </label>
            <label className="model-log-filter-field model-log-filter-field-search">
              <span>Results</span>
              <input
                type="text"
                value={filters.result_query}
                onChange={(event) => updateFilter('result_query', event.target.value)}
                placeholder="Search summaries, models, or cameras"
              />
            </label>
          </div>
          <div className="model-log-results-header">
            <h3>Log Results</h3>
            <p>
              {filteredRecords.length} matching loaded · {loadedRecords.length} loaded of {total} total records.
            </p>
            {Object.keys(rateSummary || {}).length > 0 && (
              <p className="muted-text">
                Recent cadence: {Object.entries(rateSummary).map(([stage, fps]) => `${STAGE_LABELS[stage] || stage} ${fps} fps`).join(' · ')}
              </p>
            )}
          </div>
        </div>

        {error && <div className="banner banner-error">{error}</div>}

        <div className="card model-log-card">
          <div className="model-log-table-shell">
            <div className="model-log-table">
              <div className="model-log-table-head">
                <span>Time</span>
                <span>Camera</span>
                <span>Model Type</span>
                <span>Model</span>
                <span>Frame</span>
                <span>Results</span>
              </div>
              {filteredRecords.map((record) => (
                <div key={record.id} className="model-log-row-wrap">
                  <button
                    type="button"
                    className="model-log-row"
                    onClick={() => setExpandedRowId((previous) => (previous === record.id ? null : record.id))}
                  >
                    <span>{record.created_at ? new Date(record.created_at).toLocaleString() : 'n/a'}</span>
                    <span>{record.source_label || (record.source_id ? `Source ${record.source_id}` : 'n/a')}</span>
                    <span>{STAGE_LABELS[record.stage] || record.stage}</span>
                    <span>{record.model_display_name || record.model_key}</span>
                    <span>{record.frame_id ?? 'n/a'}</span>
                    <span>{record.result_summary}</span>
                  </button>
                  {expandedRowId === record.id && (
                    <div className="model-log-detail">
                      <pre>{JSON.stringify(record.result_payload || {}, null, 2)}</pre>
                    </div>
                  )}
                </div>
              ))}
              {!isLoading && filteredRecords.length === 0 && (
                <div className="empty-state">No model log results match the current filters.</div>
              )}
            </div>
          </div>
        </div>

        <div className="control-actions model-log-actions">
          {hasMore && (
            <button
              type="button"
              className="secondary-button"
              onClick={() => setPage((previous) => previous + 1)}
              disabled={isLoading || isLoadingMore}
            >
              {isLoadingMore ? 'Loading more...' : 'Load More'}
            </button>
          )}
          {isLoading && page === 1 && (
            <div className="muted-text">Loading the most recent model results...</div>
          )}
        </div>
      </section>
    </section>
  );
};

export default ModelLogsPage;
