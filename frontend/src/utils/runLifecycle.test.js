import {
  RUN_STARTED_EVENT,
  applyOptimisticRunOverview,
} from './runLifecycle';

describe('runLifecycle', () => {
  test('applyOptimisticRunOverview marks enabled sources as initializing', () => {
    const next = applyOptimisticRunOverview({
      system_status: 'idle',
      current_run_id: null,
      sources: [
        { id: 1, enabled: true, state: 'idle' },
        { id: 2, enabled: false, state: 'disabled' },
      ],
    }, '2026-06-03_15-16-41');

    expect(next.system_status).toBe('initializing');
    expect(next.current_run_id).toBe('2026-06-03_15-16-41');
    expect(next.sources[0].state).toBe('initializing');
    expect(next.sources[1].state).toBe('disabled');
  });

  test('dispatchRunStarted emits run id on window', () => {
    const handler = jest.fn();
    window.addEventListener(RUN_STARTED_EVENT, handler);
    const { dispatchRunStarted } = require('./runLifecycle');
    dispatchRunStarted('run-abc');
    window.removeEventListener(RUN_STARTED_EVENT, handler);
    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler.mock.calls[0][0].detail.run_id).toBe('run-abc');
  });
});
