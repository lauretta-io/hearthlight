export const areOperatorModulesActive = (moduleStatus) => (
  moduleStatus?.INGESTOR === 'running'
  || moduleStatus?.ANOMALY === 'running'
);

export const isRunActiveStatus = (systemStatus, runId, moduleStatus) => (
  Boolean(runId)
  || ['running', 'initializing'].includes(systemStatus || '')
  || areOperatorModulesActive(moduleStatus)
);

export const getFrameProgress = (statusData) => {
  if (!statusData) {
    return null;
  }
  if (statusData.frame_id !== null && statusData.frame_id !== undefined) {
    return {
      current: statusData.frame_id,
      total: statusData.total_frames ?? null,
      label: 'Frame',
    };
  }
  const enabledSources = (statusData.sources || []).filter((source) => source.enabled);
  let maxProcessed = null;
  let totalFrames = null;
  enabledSources.forEach((source) => {
    if (source.frames_processed !== null && source.frames_processed !== undefined) {
      maxProcessed = maxProcessed === null
        ? source.frames_processed
        : Math.max(maxProcessed, source.frames_processed);
    }
    if (source.total_frames !== null && source.total_frames !== undefined) {
      totalFrames = source.total_frames;
    }
  });
  if (maxProcessed === null) {
    return null;
  }
  return {
    current: maxProcessed,
    total: totalFrames,
    label: 'Frames processed',
  };
};

export const formatSourceFrameProgress = (source, { runActive = false } = {}) => {
  if (
    source.frames_processed !== null
    && source.frames_processed !== undefined
  ) {
    if (source.total_frames !== null && source.total_frames !== undefined) {
      return `${source.frames_processed} / ${source.total_frames} frames`;
    }
    return `${source.frames_processed} frames processed`;
  }
  if (
    runActive
    && source.enabled
    && (source.frames_processed === 0 || source.frames_processed === null)
    && (source.capture_fps === 0 || source.capture_fps === null || source.capture_fps === undefined)
  ) {
    return 'Pipeline active — waiting for frames from the camera stream…';
  }
  if (runActive && source.enabled && source.state === 'running') {
    return 'Waiting for frame data from ingestor…';
  }
  if (runActive && source.enabled && source.state === 'initializing') {
    return 'Starting capture…';
  }
  return null;
};

export const getLiveRunHeadline = (systemStatus, runId, moduleStatus) => {
  if (!runId && areOperatorModulesActive(moduleStatus)) {
    return 'Pipeline is active. Refreshing run status from the server…';
  }
  if (!runId) {
    return null;
  }
  if (systemStatus === 'running') {
    return `Run ${runId} is processing video.`;
  }
  if (systemStatus === 'initializing') {
    return `Run ${runId} is starting workers.`;
  }
  if (systemStatus === 'stopping') {
    return `Run ${runId} is stopping.`;
  }
  return `Run ${runId} · ${systemStatus || 'active'}`;
};
