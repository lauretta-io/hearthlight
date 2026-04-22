import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useParams } from 'react-router-dom';
import '../styles/POIResultPage.css';
import EntityCard from './EntityCard';
import ErrorAlert from './ErrorAlert';
import LoadingAlert from './LoadingAlert';
import { BaseURL } from '../config';
import { formatDateTime, formatSecondsAgo, secondsSinceDateTime } from '../utils/time';

const POI = () => {
  const { poiId } = useParams();
  const [poiData, setPoiData] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!poiId) {
      setError('POI ID is missing from the URL.');
      setIsLoading(false);
      return undefined;
    }

    let isMounted = true;

    const fetchPOIData = async () => {
      try {
        const response = await fetch(`${BaseURL}/operations/poi/?poi_id=${poiId}`);
        if (!response.ok) {
          let errorMessage = 'Failed to fetch POI information';
          try {
            const errorData = await response.json();
            errorMessage = errorData.detail || errorData.message || errorMessage;
          } catch (_) {
            // Keep default message when the error body is not JSON.
          }
          throw new Error(errorMessage);
        }
        const data = await response.json();
        if (isMounted) {
          setPoiData(data);
          setError(null);
        }
      } catch (err) {
        if (isMounted) {
          setError(err.message);
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    };

    fetchPOIData();
    const intervalId = window.setInterval(fetchPOIData, 5000);

    return () => {
      isMounted = false;
      window.clearInterval(intervalId);
    };
  }, [poiId]);

  useEffect(() => {
    const intervalId = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(intervalId);
  }, []);

  if (error) return <ErrorAlert message={error} />;
  if (isLoading) return <LoadingAlert message="Loading POI Result..." />;
  if (!poiData) return <LoadingAlert message="POI data not available." />;

  const secondsSinceUpdate = poiData.seconds_since_update
    ?? secondsSinceDateTime(poiData.last_update_time, now);

  return (
    <div className="poi-result-page">
      <section className="poi-result-page__hero">
        <div>
          <p className="poi-result-page__eyebrow">POI Result</p>
          <h1>{poiData.name || `Search ${poiData.id}`}</h1>
          <p className="poi-result-page__lede">
            Review the original search crop and the entities currently matched to this POI query.
          </p>
        </div>
        <Link to="/poi" className="poi-result-page__back-link">
          Back to POI searches
        </Link>
      </section>

      <section className="poi-result-page__stats">
        <div className="poi-result-page__stat">
          <span>Search ID</span>
          <strong>POI-{poiData.id}</strong>
        </div>
        <div className="poi-result-page__stat">
          <span>Matches</span>
          <strong>{poiData.entities?.length || 0}</strong>
        </div>
        <div className="poi-result-page__stat">
          <span>Updated</span>
          <strong>
            {secondsSinceUpdate !== null && secondsSinceUpdate !== undefined
              ? formatSecondsAgo(secondsSinceUpdate)
              : 'Unknown'}
          </strong>
        </div>
      </section>

      <div className="poi-result-page__layout">
        <section className="poi-result-page__panel">
          <div className="poi-result-page__panel-header">
            <h2>Search Summary</h2>
            <p>Original reference crop and search timing details.</p>
          </div>

          <div className="poi-result-page__summary">
            <div><strong>POI ID:</strong> {poiData.id}</div>
            {poiData.name && <div><strong>Name:</strong> {poiData.name}</div>}
            {poiData.last_update_time && (
              <div><strong>Last Updated:</strong> {formatDateTime(poiData.last_update_time)}</div>
            )}
          </div>

          {poiData.crop ? (
            <div className="poi-result-page__crop">
              <img
                src={`data:image/jpeg;base64,${poiData.crop}`}
                alt={`Search crop for POI ${poiData.name || poiData.id}`}
              />
            </div>
          ) : (
            <div className="poi-result-page__empty">No reference crop is available for this search.</div>
          )}
        </section>

        <section className="poi-result-page__panel">
          <div className="poi-result-page__panel-header">
            <h2>Matched Entities</h2>
            <p>Entities currently linked to this POI search.</p>
          </div>

          {poiData.entities && poiData.entities.length > 0 ? (
            <div className="poi-result-page__entities">
              {poiData.entities.map((entityItem, index) => (
                <EntityCard key={entityItem.entity_id || `entity-${index}`} entity={entityItem} />
              ))}
            </div>
          ) : (
            <div className="poi-result-page__empty">
              No entities found matching this POI search.
            </div>
          )}
        </section>
      </div>
    </div>
  );
};

export default POI;
