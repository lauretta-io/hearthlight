import {
  formatSourceFrameProgress,
  getFrameProgress,
  getLiveRunHeadline,
  isRunActiveStatus,
} from './runActivity';

describe('runActivity', () => {
  test('isRunActiveStatus treats run id and initializing as active', () => {
    expect(isRunActiveStatus('idle', 'run-1')).toBe(true);
    expect(isRunActiveStatus('initializing', null)).toBe(true);
    expect(isRunActiveStatus('idle', null)).toBe(false);
  });

  test('isRunActiveStatus treats running operator modules as active', () => {
    expect(isRunActiveStatus('idle', null, { INGESTOR: 'running', ANOMALY: 'idle' })).toBe(true);
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
