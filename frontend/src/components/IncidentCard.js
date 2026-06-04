import React from 'react';
import { formatDateTime } from '../utils/time';
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

const IncidentCard = ({ incident, role }) => {

  const handleClick = () => {
    window.location.href = `/incident/${incident.incident_id}`;
  };
  const style = styles[incident.incident_type] || 'threat-default';
  const title = incident.display_title || threatTypeTitles[incident.incident_type] || incident.incident_type;

  return (
    <div className={`card ${style}`} onClick={handleClick}>
      <div className="card-content">
        <span className="incident-cell incident-title">{title}</span>
        {incident.delivery_summary && (
          <span className="incident-cell incident-delivery">{incident.delivery_summary}</span>
        )}
        <span className="incident-cell incident-time">{formatDateTime(incident.incident_time)}</span>
        <span className="incident-cell incident-camera">Camera {incident.location.camera_id}</span>
        <span className={`incident-cell incident-level${!incident.alert_level ? ' incident-level-empty' : ''}`}>{incident.alert_level}</span>
        {role && <span className="incident-cell incident-role">{role}</span>}
        <span className="incident-cell incident-id">{incident.incident_id}</span>
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
