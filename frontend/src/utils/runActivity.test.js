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
      { enabled: true, state: 'running', frames_processed: null },
      { runActive: true },
    )).toMatch(/Waiting for frame data/i);
  });

  test('getLiveRunHeadline reflects steady running state', () => {
    expect(getLiveRunHeadline('running', '2026-06-03_15-20-51')).toMatch(/processing video/i);
  });
});
