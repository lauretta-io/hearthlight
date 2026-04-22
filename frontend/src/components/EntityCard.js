import React from 'react';
import { formatDateTime } from '../utils/time';
import '../styles/IncidentCard.css';


const EntityCard = ({ entity, role }) => {
  // Check if entity ID ends with a negative number
  const endsWithNegativeNumber = /--\d+$/.test(entity.entity_id);
  
  const handleClick = () => {
    // Only navigate if it doesn't end with a negative number
    if (!endsWithNegativeNumber) {
      window.location.href = `/entity/${entity.entity_id}`;
    }
  };
  
  return (
    <div 
      className={`card ${endsWithNegativeNumber ? 'card-disabled' : ''}`} 
      onClick={handleClick}
      style={endsWithNegativeNumber ? { 
        opacity: 0.6, 
        cursor: 'default' 
      } : { 
        cursor: 'pointer' 
      }}
    >
      <div className="card-content">
        <p>Entity ID: {endsWithNegativeNumber ? "NOT YET IDENTIFIED" : entity.entity_id}</p>
        {role && <p>Role: {role}</p>}
        <p>Camera: {entity.location?.camera_id}</p>
        <p>Last Seen: {formatDateTime(entity.last_seen_time)}</p>
      </div>
      {entity.crop && (
        <div className="media-container">
          <div className="image-wrapper">
            <img
              src={`data:image/jpeg;base64,${entity.crop}`}
              alt="Entity"
            />
          </div>
        </div>
      )}
    </div>
  );
};

export default EntityCard;
