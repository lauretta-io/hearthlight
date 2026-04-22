import { BaseURL } from '../config';

export const resolveIncident = async (incidentId) => {
  try {
    const currentTime = new Date().toUTCString();
    const response = await fetch(`${BaseURL}/genetec/update_incident`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(
        {
          incident_id: incidentId,
          new_status: 'RESOLVED',
          update_time: currentTime,
        }),
    });

    if (!response.ok) {
      console.error('Failed to resolve the incident');
    }
  } catch (error) {
    console.error('Error occurred while resolving the incident:', error);
  }
};
