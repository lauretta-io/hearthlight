import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import 'vidstack/styles/defaults.css';
import 'vidstack/styles/community-skin/video.css';
import '../styles/HistoryCard.css';
import { MediaCommunitySkin, MediaOutlet, MediaPlayer, MediaPoster } from '@vidstack/react';
import IncidentCard from './IncidentCard';
import EntityCard from './EntityCard';
import ErrorAlert from './ErrorAlert';
import LoadingAlert from './LoadingAlert';
import { BaseURL } from '../config'
import { resolveIncident } from '../utils/api';


const Incident = () => {
  const { incidentId } = useParams();
  const [incident, setIncident] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchIncident = async () => {
      setIsLoading(true);
      try {
        const response = await fetch(`${BaseURL}/operations/incident/?incident_id=${incidentId}`);
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

  const handleResolve = (() => resolveIncident(incident.incident_id));
  console.log(incident.entities);

  return (
    <div className="history-container">
      <h1 className="history-title">Trigger {incidentId}</h1>
      <div className="history-content">
        <div className="video-wrapper">
          <div className="video-container">
            <MediaPlayer
              key={incidentId}
              src={`${BaseURL}/operations/incident_video/?incident_id=${incidentId}`}
              aspectRatio={16 / 9}
              crossorigin=""
            >
              <MediaOutlet>
                <MediaPoster alt="Video Description" />
              </MediaOutlet>
              <MediaCommunitySkin />
            </MediaPlayer>
          </div>
        </div>
        <div className="history-list">
          <IncidentCard incident={incident} onResolve={handleResolve} includeResolve={true} />
        </div>

        <h1 className="history-title">Entities Involved</h1>
        <div className="history-list">
          {incident.entities.map((item, index) => (
            <EntityCard key={index} entity={item.entity} role={item.role} />
          ))}
        </div>
      </div>
    </div>
  );
};

export default Incident;
