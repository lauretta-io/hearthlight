import { useState, useEffect } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import 'vidstack/styles/defaults.css';
import 'vidstack/styles/community-skin/video.css';
import '../styles/HistoryCard.css';
import { MediaCommunitySkin, MediaOutlet, MediaPlayer, MediaPoster } from '@vidstack/react';
import IncidentCard from './IncidentCard';
import ErrorAlert from './ErrorAlert';
import LoadingAlert from './LoadingAlert';
import { BaseURL } from '../config'


const Incident = () => {
  const { incidentId } = useParams();
  const location = useLocation();
  const [incident, setIncident] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchIncident = async () => {
      setIsLoading(true);
      try {
        const response = await fetch(`${BaseURL}/operations/incident?incident_id=${incidentId}`);
        if (!response.ok) {
          throw new Error('Failed to fetch incident information');
        }
        const data = await response.json();
        setIncident(data);
      } catch (error) {
        setError(error.message);
      } finally {
        setIsLoading(false);
      }
    };

    fetchIncident();
  }, [incidentId]);

  if (error) return <ErrorAlert message={error} />;
  if (isLoading) return <LoadingAlert message="Loading trigger..." />;

  const mediaType = incident.media_type || (incident.incident_type === 'ANOMALY' ? 'video' : 'image');
  const anomalyVideoUrl = incident.media_event_id && incident.run_identifier
    ? `${BaseURL}/operations/anomaly_video/?event_id=${encodeURIComponent(incident.media_event_id)}&run_identifier=${encodeURIComponent(incident.run_identifier)}&duration=10`
    : null;
  const backTarget = `/incidents${location.search || '?tab=monitoring'}`;

  return (
    <div className="history-container">
      <Link to={backTarget} className="back-link">Back to Trigger List</Link>
      <h1 className="history-title">Trigger {incidentId}</h1>
      <div className="history-content">
        <div className="video-wrapper">
          <div className="video-container">
            {mediaType === 'image' ? (
              <img
                className="history-detail-image"
                src={`${BaseURL}/operations/incident_image/?incident_id=${incidentId}`}
                alt={incident.display_title || `Trigger ${incidentId}`}
              />
            ) : (
              <MediaPlayer
                key={incidentId}
                src={anomalyVideoUrl || `${BaseURL}/operations/incident_video/?incident_id=${incidentId}`}
                aspectRatio={16 / 9}
                crossorigin=""
              >
                <MediaOutlet>
                  <MediaPoster alt="Video Description" />
                </MediaOutlet>
                <MediaCommunitySkin />
              </MediaPlayer>
            )}
          </div>
        </div>
        <div className="history-list">
          <IncidentCard incident={incident} />
        </div>

        <h1 className="history-title">Connectors Triggered</h1>
        <div className="history-connector-panel">
          {incident.delivery_summary ? (
            <p>{incident.delivery_summary}</p>
          ) : (
            <p>No connector delivery has been recorded for this trigger.</p>
          )}
        </div>
      </div>
    </div>
  );
};

export default Incident;
