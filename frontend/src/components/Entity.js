import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import '../styles/HistoryCard.css';
import IncidentCard from './IncidentCard';
import EntityCard from './EntityCard';
import JourneyCard from './JourneyCard';
import ErrorAlert from './ErrorAlert';
import LoadingAlert from './LoadingAlert';
import { BaseURL } from '../config'


const Entity = () => {
  const { entityId } = useParams();
  const [entity, setEntity] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchEntity = async () => {
      setIsLoading(true);
      try {
        const response = await fetch(`${BaseURL}/operations/entity/?entity_id=${entityId}`);
        if (!response.ok) {
          throw new Error('Failed to fetch entity information');
        }
        const data = await response.json();
        setEntity(data);
      } catch (error) {
        setError(error.message);
      } finally {
        setIsLoading(false);
      }
    };

    fetchEntity();
  }, [entityId]);

  if (error) return <ErrorAlert message={error} />;
  if (isLoading) return <LoadingAlert message="Loading entity..." />;

  return (
    <div className="history-container">
      <h1 className="history-title">Entity {entityId}</h1>
      <div className="history-content">
        {
          entity.associated_incidents && (
            <div>
              <h2>Incidents</h2>
              <div className="history-list">
                {
                  entity.associated_incidents.map((item) => (
                    <IncidentCard
                      key={item.incident.incident_id}
                      incident={item.incident}
                      role={item.role}
                    />
                  ))
                }
              </div>
            </div>
          )
        }
        {
          entity.associated_entities && (
            <div>
              <h2>Associated Entities</h2>
              <div className="history-list">
                {
                  entity.associated_entities.map((entity) => (
                    <EntityCard
                      key={entity.entity_id}
                      entity={entity}
                    />
                  ))
                }
              </div>
            </div>
          )
        }
        {
          entity.journey && (
            <div>
              <h2>Journey</h2>
              <div className="history-list">
                {
                  entity.journey.map((item, index) => (
                    <JourneyCard
                      key={`journey-${index}`}
                      journey={item}
                    />
                  ))
                }
              </div>
            </div>
          )
        }
      </div>
    </div>
  );
};

export default Entity;
