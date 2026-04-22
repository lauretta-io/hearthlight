import React, { useEffect, useMemo, useState } from 'react';
import { BaseURL } from '../config';
import '../styles/LivePage.css';

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
    return 'The backend preview stream could not be opened. Check that the source is reachable from the backend container.';
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

const LivePage = () => {
  const [sources, setSources] = useState([]);
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
        setSources(Array.isArray(data) ? data : []);
        setPreviewFailures({});
        setError(null);
      } catch (loadError) {
        if (active) {
          setError(loadError.message);
        }
      }
    };

    loadSources();
    const intervalId = window.setInterval(loadSources, 5000);

    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, []);

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
          <span>Auto-refreshes every 5 seconds</span>
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
            const supportMessage = getSupportMessage(source, previewFailures[source.id]);

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
                      <p>{supportMessage}</p>
                    </div>
                  ) : (
                    <img
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
                  <span><strong>Tasks:</strong> {(source.tasks || []).join(', ') || 'n/a'}</span>
                  <span><strong>Source:</strong> {getSourceDescription(source)}</span>
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
