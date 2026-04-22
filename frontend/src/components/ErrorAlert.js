import React from 'react';

const ErrorAlert = ({ message }) => (
  <div className="error-alert">
    <div className="error-content">
      <div className="error-icon">!</div>
      <div className="error-message">{message}</div>
    </div>
  </div>
);

export default ErrorAlert;
