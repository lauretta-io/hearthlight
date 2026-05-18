import React from 'react';
import RunSection from './RunSection';
import MonitoringSection from './MonitoringSection';

const MonitoringPage = () => (
  <>
    <RunSection embedded pollingEnabled showHeader={false} />
    <MonitoringSection embedded pollingEnabled />
  </>
);

export default MonitoringPage;
