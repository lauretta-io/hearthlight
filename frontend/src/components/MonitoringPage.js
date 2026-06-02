import React from 'react';
import MonitoringSection from './MonitoringSection';

const MonitoringPage = ({ pollingEnabled = true }) => (
  <MonitoringSection embedded pollingEnabled={pollingEnabled} />
);

export default MonitoringPage;
