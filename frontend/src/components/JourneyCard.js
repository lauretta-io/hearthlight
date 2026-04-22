import React from 'react';
import { formatDateTime } from '../utils/time';
import '../styles/HistoryCard.css';


const JourneyCard = ({ journey }) => {

  return (
    <div className={`history-card `}>
      <div className="history-card card-content">
        <p>Camera ID: {journey.location.camera_id}</p>
        <p>Enter Time: {formatDateTime(journey.start_time)}</p>
        <p>Exit Time: {formatDateTime(journey.stop_time)}</p>
      </div>
      {
        journey.crop && (
          <div className="history-card media-container">
            <div className="history-card image-wrapper">
              <img
                src={`data:image/jpeg;base64,${journey.crop}`}
                alt={`Image of entity in ${journey.location.camera_id}`}
              />
            </div>
          </div>
        )
      }
    </div>
  );
};

export default JourneyCard;
