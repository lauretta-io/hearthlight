import React, { useEffect, useMemo, useState } from 'react';
import { BaseURL } from '../config';
import { formatSourceFrameProgress } from '../utils/runActivity';
import { RUN_STARTED_EVENT } from '../utils/runLifecycle';
import { subscribeToOperationsEvent } from '../utils/sharedEvents';
import { subscribeToSharedPoll } from '../utils/sharedPolling';
import '../styles/LivePage.css';

const REFRESH_INTERVAL_MS = 1500;
const STATUS_POLL_MS = 2000;

const getPreviewUrl = (source) => {
  if (!source.id) {
    return null;
  }
  return `${BaseURL}/sources/${source.id}/preview.mjpeg`;
};

const getSupportMessage = (source, previewFailed) => {
  if (!source.id) {
    return 'This source is missing a stable identifier, so a preview stream cannot be requested.';
  }
  if (previewFailed) {
    return 'The preview stream could not be opened. If a run is active, stop it and refresh — the webcam may already be in use. Otherwise confirm the source is reachable from this machine.';
  }
  return null;
};

const getSourceDescription = (source) => {
  if (source.kind === 'video_upload') {
    return source.upload?.original_filename || 'uploaded video file';
  }
  if (source.kind === 'webcam') {
    return source.source_value ?? 'host-local webcam';
  }
  return source.source_value ?? 'n/a';
};

const areSourcesEquivalent = (left, right) => (
  left?.id === right?.id
  && left?.kind === right?.kind
  && left?.label === right?.label
  && Boolean(left?.enabled) === Boolean(right?.enabled)
  && left?.source_value === right?.source_value
  && left?.upload_id === right?.upload_id
  && left?.order === right?.order
  && left?.frame_processing_mode === right?.frame_processing_mode
  && left?.process_every_n_frames === right?.process_every_n_frames
  && left?.target_frame_rate === right?.target_frame_rate
  && left?.detector_model_key === right?.detector_model_key
  && left?.tracker_model_key === right?.tracker_model_key
  && left?.anomaly_stage_1_model_key === right?.anomaly_stage_1_model_key
  && left?.anomaly_stage_2_model_key === right?.anomaly_stage_2_model_key
  && left?.upload?.original_filename === right?.upload?.original_filename
);

const mergeSources = (previousSources, nextSources) => {
  const previousById = new Map(previousSources.map((source) => [source.id, source]));
  return nextSources.map((source) => {
    const previous = previousById.get(source.id);
    if (previous && areSourcesEquivalent(previous, source)) {
      return previous;
    }
    return source;
  });
};

const LivePage = () => {
  const [sources, setSources] = useState([]);
  const [runStatus, setRunStatus] = useState(null);
  const [error, setError] = useState(null);
  const [previewFailures, setPreviewFailures] = useState({});

  useEffect(() => {
    let active = true;

    const loadSources = async () => {
      try {
        const response = await fetch(`${BaseURL}/settings/input-sources`);
        if (!response.ok) {
          throw new Error('Failed to load camera sources');
        }
        const data = await response.json();
        if (!active) {
          return;
        }
        setSources((currentSources) => mergeSources(currentSources, Array.isArray(data) ? data : []));
        setError(null);
      } catch (loadError) {
        if (active) {
          setError(loadError.message);
        }
      }
    };

    const unsubscribePoll = subscribeToSharedPoll(
      'live-sources',
      REFRESH_INTERVAL_MS,
      loadSources,
      { runImmediately: true },
    );
    const refreshSources = () => {
      loadSources();
    };
    const unsubscribeSnapshot = subscribeToOperationsEvent('snapshot', refreshSources);
    const unsubscribeRuns = subscribeToOperationsEvent('runs.updated', refreshSources);
    const unsubscribeIncidents = subscribeToOperationsEvent('incidents.updated', refreshSources);

    return () => {
      active = false;
      unsubscribePoll();
      unsubscribeSnapshot();
      unsubscribeRuns();
      unsubscribeIncidents();
    };
  }, []);

  useEffect(() => {
    let active = true;

    const loadRunStatus = async () => {
      try {
        const response = await fetch(`${BaseURL}/status`);
        if (!response.ok) {
          throw new Error('Failed to fetch run status');
        }
        const data = await response.json();
        if (active) {
          setRunStatus(data);
        }
      } catch (_statusError) {
        if (active) {
          setRunStatus((previous) => previous);
        }
      }
    };

    const unsubscribePoll = subscribeToSharedPoll(
      'live-run-status',
      STATUS_POLL_MS,
      loadRunStatus,
      { runImmediately: true },
    );
    const refreshStatus = () => {
      loadRunStatus();
    };
    window.addEventListener(RUN_STARTED_EVENT, refreshStatus);

    return () => {
      active = false;
      unsubscribePoll();
      window.removeEventListener(RUN_STARTED_EVENT, refreshStatus);
    };
  }, []);

  const runtimeSourcesById = useMemo(() => (
    (runStatus?.sources || []).reduce((result, source) => {
      if (source.id !== null && source.id !== undefined) {
        result[source.id] = source;
      }
      return result;
    }, {})
  ), [runStatus?.sources]);

  const liveSources = useMemo(() => {
    const enabledSources = sources.filter((source) => source.enabled);
    const primaryLiveSources = enabledSources
      .filter((source) => source.kind !== 'video_upload')
      .slice(0, 2);
    const uploadedVideoSources = enabledSources
      .filter((source) => source.kind === 'video_upload');
    return [...primaryLiveSources, ...uploadedVideoSources];
  }, [sources]);

  return (
    <section className="live-page">
      <div className="live-page__header">
        <div>
          <h2>Live Video</h2>
          <p className="live-page__subtitle">
            Preview the first two enabled live camera streams and all enabled uploaded videos configured in Settings.
          </p>
        </div>
        <div className="live-page__meta">
          <span>{liveSources.length} live source{liveSources.length === 1 ? '' : 's'}</span>
          <span>Warm refreshes in the background</span>
        </div>
      </div>

      {error && (
        <div className="live-page__alert live-page__alert--error">{error}</div>
      )}

      {liveSources.length === 0 ? (
        <div className="live-page__empty">
          No enabled live sources are available yet. Add or enable camera URLs, webcams, or uploaded videos in Settings.
        </div>
      ) : (
        <div className="live-page__grid">
          {liveSources.map((source) => {
            const previewUrl = getPreviewUrl(source);
            const runtimeSource = runtimeSourcesById[source.id] || source;
            const frameProgressText = formatSourceFrameProgress(runtimeSource, {
              runActive: Boolean(runStatus?.run_id),
            });
            const previewKey = `${source.id}-${runStatus?.run_id || 'idle'}`;
            const supportMessage = getSupportMessage(source, previewFailures[source.id]);
            const runActivePreviewBlocked = Boolean(
              runStatus?.run_id
              && previewFailures[source.id]
              && source.kind !== 'video_upload',
            );

            return (
              <article key={source.id || source.label} className="live-card">
                <div className="live-card__header">
                  <div>
                    <h3>{source.label || 'Unnamed Source'}</h3>
                    <p>{source.kind}</p>
                  </div>
                  <div className="live-card__badge">
                    {source.enabled ? 'enabled' : 'disabled'}
                  </div>
                </div>

                <div className="live-card__viewer">
                  {supportMessage ? (
                    <div className="live-card__unsupported">
                      <strong>Inline preview unavailable</strong>
                      <p>
                        {runActivePreviewBlocked
                          ? 'This stream is already attached to the active run, so a second browser preview cannot stay open. Processing continues in the background — use the frame counter below to confirm progress.'
                          : supportMessage}
                      </p>
                    </div>
                  ) : (
                    <img
                      key={previewKey}
                      className="live-card__media"
                      src={previewUrl}
                      alt={`${source.label} live stream`}
                      onError={() => {
                        setPreviewFailures((currentFailures) => ({
                          ...currentFailures,
                          [source.id]: true,
                        }));
                      }}
                      onLoad={() => {
                        setPreviewFailures((currentFailures) => {
                          if (!currentFailures[source.id]) return currentFailures;
                          const next = { ...currentFailures };
                          delete next[source.id];
                          return next;
                        });
                      }}
                    />
                  )}
                </div>

                <div className="live-card__details">
                  <span><strong>Source:</strong> {getSourceDescription(source)}</span>
                  {frameProgressText && (
                    <span><strong>Frames:</strong> {frameProgressText}</span>
                  )}
                  <span>
                    <strong>Processing:</strong>{' '}
                    {source.effective_frame_processing_mode === 'target_frame_rate'
                      ? `Target ${source.target_frame_rate || source.processed_fps || 0} FPS`
                      : `Every ${source.effective_process_every_n_frames || source.process_every_n_frames || 1} frame(s)`}
                  </span>
                  {source.processed_fps ? (
                    <span><strong>Processed:</strong> {source.processed_fps} FPS</span>
                  ) : null}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
};

export default LivePage;
