import React from 'react';
import { formatDateTime } from '../utils/time';
import { resolveIncident } from '../utils/api';
import '../styles/IncidentCard.css';


const styles = {
  'GUN': 'threat-gun',
  'FARE JUMPER': 'fare-jumper',
  'UNATTENDED BAG': 'threat-unattended-bag',
  'UNATTENDED CHILD': 'threat-unattended-child',
  'UNATTENDED TRAY': 'threat-unattended-tray',
  'STOLEN TRAY': 'stolen-tray',
};

const threatTypeTitles = {
  'GUN': 'Gun Detected',
  'FARE JUMPER': 'Fare Jumper',
  'UNATTENDED BAG': 'Unattended Bag',
  'UNATTENDED CHILD': 'Unattended Child',
  'UNATTENDED TRAY': 'Unattended Tray',
  'STOLEN TRAY': 'Stolen Tray',
  'ALERT': 'Alert',
};

const IncidentCard = ({ incident, role, includeResolve }) => {

  const handleClick = () => {
    window.location.href = `/incident/${incident.incident_id}`;
  };

  const handleResolve = (e) => {
    e.stopPropagation();
    resolveIncident(incident.incident_id);
  };
  const style = styles[incident.incident_type] || 'threat-default';
  const isResolved = incident.status === 'RESOLVED' || incident.status === 'PENDING RESOLUTION';

  return (
    <div className={`card ${style}`} onClick={handleClick}>
      <div className="card-content">
        <p>{incident.display_title || threatTypeTitles[incident.incident_type] || incident.incident_type}</p>
        <p>{formatDateTime(incident.incident_time)}</p>
        {incident.alert_level && <p>Level: {incident.alert_level}</p>}
        {role && <p>Role: {role}</p>}
        <p>Camera ID: {incident.location.camera_id}</p>
        <p>Trigger ID: {incident.incident_id}</p>
        <p className={`status ${isResolved ? 'resolved' : 'unresolved'}`}>
          Status: {isResolved ? 'Resolved' : 'Unresolved'}
        </p>
    {includeResolve &&
        <button className="resolve-button" onClick={handleResolve}>
          Resolve
        </button>
    }
      </div>
      {incident.crop && (
        <div className="media-container">
          <div className="image-wrapper">
            <img
              src={`data:image/jpeg;base64,${incident.crop}`}
              alt="Trigger"
            />
          </div>
        </div>
      )}
    </div>
  );
};

export default IncidentCard;
