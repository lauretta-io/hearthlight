import {
  formatSourceFrameProgress,
  getFrameProgress,
  getLiveRunHeadline,
  isRunActiveStatus,
  resolveDisplaySystemStatus,
} from './runActivity';

describe('runActivity', () => {
  test('isRunActiveStatus treats run id and initializing as active', () => {
    expect(isRunActiveStatus('idle', 'run-1')).toBe(true);
    expect(isRunActiveStatus('initializing', null)).toBe(true);
    expect(isRunActiveStatus('idle', null)).toBe(false);
  });

  test('isRunActiveStatus requires run id or initializing for idle ingestor-only activity', () => {
    expect(isRunActiveStatus('idle', null, { INGESTOR: 'running', ANOMALY: 'running' })).toBe(false);
    expect(isRunActiveStatus('running', 'run-1', { INGESTOR: 'running' })).toBe(true);
  });

  test('resolveDisplaySystemStatus does not treat anomaly-only as running', () => {
    expect(resolveDisplaySystemStatus({
      system_status: 'idle',
      current_run_id: null,
      resources: { module_status: { INGESTOR: 'idle', ANOMALY: 'running' } },
    })).toBe('idle');
    expect(resolveDisplaySystemStatus({
      system_status: 'idle',
      current_run_id: 'run-1',
      resources: { module_status: { INGESTOR: 'running' } },
    })).toBe('running');
  });

  test('getFrameProgress falls back to per-source processed frames', () => {
    const progress = getFrameProgress({
      frame_id: null,
      sources: [
        { enabled: true, frames_processed: 12, total_frames: null },
        { enabled: true, frames_processed: 18, total_frames: 100 },
      ],
    });
    expect(progress).toEqual({
      current: 18,
      total: 100,
      label: 'Frames processed',
    });
  });

  test('formatSourceFrameProgress shows waiting copy while running without counts', () => {
    expect(formatSourceFrameProgress(
      { enabled: true, state: 'running', frames_processed: null, capture_fps: 0 },
      { runActive: true },
    )).toMatch(/waiting for frames/i);
    expect(formatSourceFrameProgress(
      { enabled: true, state: 'running', frames_processed: 0, capture_fps: 0 },
      { runActive: true },
    )).toBe('0 frames processed');
  });

  test('getLiveRunHeadline reflects steady running state', () => {
    expect(getLiveRunHeadline('running', '2026-06-03_15-20-51')).toMatch(/processing video/i);
  });
});
