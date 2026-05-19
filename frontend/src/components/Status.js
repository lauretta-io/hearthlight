import React, { useEffect, useState } from 'react';
import { BaseURL } from '../config';

const formatPercent = (value) => (
  value === null || value === undefined ? 'n/a' : `${value.toFixed(1)}%`
);
const OPERATOR_MODULES = ['INGESTOR', 'ANOMALY'];

const getIngestorExplanation = ({ moduleStatus, systemStatus, admission }) => {
  const ingestorState = moduleStatus?.INGESTOR;
  if (!ingestorState || ingestorState === 'running') {
    return null;
  }
  if (ingestorState === 'error') {
    return 'Ingestor reported an error. Video frames are not being read or published into the pipeline.';
  }
  if (ingestorState === 'stopped') {
    return null;
  }
  if (systemStatus === 'initializing') {
    return 'Ingestor is still starting. It should switch to running after the pipeline workers finish booting.';
  }
  if (systemStatus === 'idle') {
    if (admission?.reason) {
      return `Ingestor is idle because the pipeline has not started. Current blocker: ${admission.reason}`;
    }
    return 'Ingestor is idle because no active run is feeding video into the pipeline yet.';
  }
  return 'Ingestor is not actively processing frames right now.';
};

const getPipelineBackpressureHint = (statusData) => {
  const ingestorMetrics = statusData.resources?.module_metrics?.INGESTOR;
  const queueDepth = Number(ingestorMetrics?.queue_depths?.frames_thread || 0);
  if (statusData.status === 'running' && queueDepth >= 5) {
    return `Detector is still working through queued frames (${queueDepth} waiting). On CPU localhost demos, use a smaller stream or CPU fallback image size if this stays high.`;
  }
  return null;
};

const Status = () => {
  const [statusData, setStatusData] = useState({
    status: 'loading',
    frame_id: null,
    total_frames: null,
    module_status: {},
    resources: null,
    admission: null,
    run_id: null,
  });

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const response = await fetch(`${BaseURL}/status`);
        if (!response.ok) {
          throw new Error('Failed to fetch status');
        }
        const data = await response.json();
        setStatusData(data);
      } catch (error) {
        setStatusData((previous) => ({
          ...previous,
          status: 'error',
        }));
      }
    };

    fetchStatus();
    const intervalId = window.setInterval(fetchStatus, 1000);
    return () => window.clearInterval(intervalId);
  }, []);

  const progressValue =
    statusData.frame_id !== null && statusData.total_frames
      ? Math.min((statusData.frame_id / statusData.total_frames) * 100, 100)
      : 0;
  const dependencyStatus = Object.entries(statusData.resources?.dependency_status || {});
  const moduleMetrics = Object.entries(statusData.resources?.module_metrics || {}).filter(
    ([name]) => OPERATOR_MODULES.includes(name),
  );
  const ingestorExplanation = getIngestorExplanation({
    moduleStatus: statusData.module_status,
    systemStatus: statusData.status,
    admission: statusData.admission,
  });
  const backpressureHint = getPipelineBackpressureHint(statusData);

  return (
    <div className="status-container">
      <div className="status-header">
        <div>
          <span className="status-text">System: {statusData.status}</span>
          <span className="status-detail">
            {statusData.run_id ? `Run ${statusData.run_id}` : 'No active run'}
          </span>
        </div>
        <div className="status-summary">
          <span>CPU {formatPercent(statusData.resources?.cpu_percent)}</span>
          <span>Memory {formatPercent(statusData.resources?.memory_percent)}</span>
          <span>
            Admission {statusData.admission?.allowed ? 'open' : 'blocked'}
          </span>
        </div>
      </div>

      <div className="module-summary">
        {Object.entries(statusData.module_status || {})
          .filter(([moduleName]) => OPERATOR_MODULES.includes(moduleName))
          .map(([moduleName, moduleState]) => (
          <span key={moduleName} className={`module-pill module-${moduleState}`}>
            {moduleName}: {moduleState}
          </span>
        ))}
      </div>

      {dependencyStatus.length > 0 && (
        <div className="module-summary">
          {dependencyStatus.map(([name, dependency]) => (
            <span
              key={name}
              className={`module-pill module-${dependency.status === 'ok' ? 'running' : 'error'}`}
            >
              {name}: {dependency.status}
            </span>
          ))}
        </div>
      )}

      {moduleMetrics.length > 0 && (
        <div className="module-summary">
          {moduleMetrics.map(([name, metrics]) => (
            <span
              key={name}
              className={`module-pill module-${metrics.state === 'ok' ? 'running' : metrics.state}`}
            >
              {name}: {metrics.state}
            </span>
          ))}
        </div>
      )}

      {statusData.admission?.reason && !statusData.admission.allowed && (
        <div className="status-warning">{statusData.admission.reason}</div>
      )}

      {ingestorExplanation && (
        <div className="status-warning">{ingestorExplanation}</div>
      )}

      {backpressureHint && (
        <div className="status-warning">{backpressureHint}</div>
      )}

      {statusData.frame_id !== null && (
        <div className="frame-progress">
          <span className="frame-count">
            Frame: {statusData.frame_id}
            {statusData.total_frames !== null && ` / ${statusData.total_frames}`}
          </span>
          {statusData.total_frames !== null && (
            <div className="progress-container">
              <div
                className="progress-bar"
                style={{ width: `${progressValue}%` }}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default Status;
