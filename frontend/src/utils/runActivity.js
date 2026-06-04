export const isIngestorProcessing = (moduleStatus) => (
  moduleStatus?.INGESTOR === 'running'
);

export const isAnyPipelineModuleRunning = (moduleStatus) => (
  moduleStatus?.INGESTOR === 'running'
  || moduleStatus?.ANOMALY === 'running'
  || moduleStatus?.REID === 'running'
  || moduleStatus?.ASSOCIATION === 'running'
);

export const resolveDisplaySystemStatus = (overviewOrStatus) => {
  const systemStatus = overviewOrStatus?.system_status ?? overviewOrStatus?.status ?? 'idle';
  const runId = overviewOrStatus?.current_run_id ?? overviewOrStatus?.run_id ?? null;
  const moduleStatus = overviewOrStatus?.resources?.module_status
    ?? overviewOrStatus?.module_status
    ?? {};
  // If API reports no current run, treat the system as idle even if some module
  // status value is stale (e.g. a worker didn't publish a final STOPPED message
  // yet). The UI should key off `current_run_id` as the source-of-truth.
  if (!runId) {
    return 'idle';
  }
  if (systemStatus === 'idle' && isIngestorProcessing(moduleStatus)) {
    return 'running';
  }
  return systemStatus || 'idle';
};

export const isRunActiveStatus = (systemStatus, runId, moduleStatus) => {
  // If we have a run id, treat it as authoritative that some run context exists.
  // The backend can temporarily report `system_status: idle` between transitions,
  // but the run id should still keep the UI in an "active" state.
  if (runId) {
    return true;
  }
  const resolved = resolveDisplaySystemStatus({
    system_status: systemStatus,
    current_run_id: runId,
    resources: { module_status: moduleStatus },
  });
  // Treat explicit initialization as active even before the backend has
  // reported a run id, but do not treat 'idle' + stale module status as active.
  if (systemStatus === 'initializing' || resolved === 'initializing') {
    return true;
  }
  return ['running', 'stopping'].includes(resolved);
};

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

export const getIngestorBackpressureHint = (statusData) => {
  const metrics = statusData?.resources?.module_metrics?.INGESTOR
    || statusData?.module_metrics?.INGESTOR;
  const queueDepth = Number(metrics?.queue_depths?.downstream_max || 0);
  const phase = metrics?.processing_phase || metrics?.hottest_queue;
  if (queueDepth >= 5) {
    return `Pipeline is processing earlier frames (queue depth ${queueDepth}). The counter updates when the next frame finishes.`;
  }
  if (phase === 'detecting') {
    return 'Running detector on the current frame…';
  }
  if (phase === 'downstream_backpressure') {
    return 'Waiting for tracker/anomaly workers to catch up…';
  }
  return null;
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
  const displayStatus = resolveDisplaySystemStatus({
    system_status: systemStatus,
    current_run_id: runId,
    resources: { module_status: moduleStatus },
  });
  if (!runId) {
    return null;
  }
  if (displayStatus === 'running') {
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
