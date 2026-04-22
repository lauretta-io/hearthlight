import React from 'react';
import { formatDateTime, formatSecondsAgo, secondsSinceDateTime } from '../utils/time';


const POICard = ({ poiCard }) => {
  const secondsSinceUpdate = poiCard.seconds_since_update
    ?? secondsSinceDateTime(poiCard.last_update_time);

  const handleClick = () => {
    window.location.href = `/poi/${poiCard.id}`;
  };

  return (
    <button type="button" className="poi-result-card" onClick={handleClick}>
      <div className="poi-result-card__media">
        {poiCard.crop ? (
          <img
            src={`data:image/jpeg;base64,${poiCard.crop}`}
            alt={`POI search ${poiCard.name || poiCard.id}`}
          />
        ) : (
          <div className="poi-result-card__placeholder">No preview</div>
        )}
      </div>

      <div className="poi-result-card__body">
        <div className="poi-result-card__eyebrow">POI-SEARCH-{poiCard.id}</div>
        <h3 className="poi-result-card__title">{poiCard.name}</h3>
        <div className="poi-result-card__meta">
          <div><strong>{poiCard.num_entities}</strong> matched entities</div>
          {secondsSinceUpdate !== null && secondsSinceUpdate !== undefined && (
            <div>Updated {formatSecondsAgo(secondsSinceUpdate)}</div>
          )}
          {poiCard.last_update_time && (
            <div>Last result {formatDateTime(poiCard.last_update_time)}</div>
          )}
        </div>
      </div>
    </button>
  );
};

export default POICard;
