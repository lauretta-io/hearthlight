describe('shared polling coordinator', () => {
  beforeEach(() => {
    jest.resetModules();
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  test('shares one interval across subscribers for the same key', () => {
    const { subscribeToSharedPoll } = require('./sharedPolling');
    const first = jest.fn();
    const second = jest.fn();

    const unsubscribeFirst = subscribeToSharedPoll('status', 1000, first, { runImmediately: true });
    const unsubscribeSecond = subscribeToSharedPoll('status', 1000, second);

    expect(first).toHaveBeenCalledTimes(1);
    jest.advanceTimersByTime(1000);
    expect(first).toHaveBeenCalledTimes(2);
    expect(second).toHaveBeenCalledTimes(1);

    unsubscribeFirst();
    unsubscribeSecond();
  });
});
