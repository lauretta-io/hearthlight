const browserBaseURL = () => {
  if (typeof window === 'undefined') {
    return 'http://localhost:8000';
  }
  return `${window.location.protocol}//${window.location.hostname}:8000`;
};

export const BaseURL = process.env.REACT_APP_API_BASE_URL || browserBaseURL();
