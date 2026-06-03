export const isRunActiveStatus = (systemStatus, runId) => (
  Boolean(runId)
  || ['running', 'initializing'].includes(systemStatus || '')
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
  if (runActive && source.enabled && source.state === 'running') {
    return 'Waiting for frame data from ingestor…';
  }
  if (runActive && source.enabled && source.state === 'initializing') {
    return 'Starting capture…';
  }
  return null;
};

export const getLiveRunHeadline = (systemStatus, runId) => {
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
