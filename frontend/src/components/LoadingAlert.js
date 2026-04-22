import React from 'react';

const LoadingAlert = ({ message }) => (
  <div className="loading-alert">
    <div className="loading-content">
      <div className="loading-icon">!</div>
      <div className="loading-message">{message}</div>
    </div>
  </div>
);

export default LoadingAlert;
