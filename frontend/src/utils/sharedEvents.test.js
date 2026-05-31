describe('shared operations event client', () => {
  beforeEach(() => {
    jest.resetModules();
  });

  afterEach(() => {
    delete global.EventSource;
  });

  test('reuses one EventSource across multiple subscriptions', () => {
    const addEventListener = jest.fn();
    const close = jest.fn();
    global.EventSource = jest.fn(() => ({
      addEventListener,
      close,
    }));

    const { subscribeToOperationsEvent } = require('./sharedEvents');

    const unsubscribeOne = subscribeToOperationsEvent('snapshot', jest.fn());
    const unsubscribeTwo = subscribeToOperationsEvent('runs.updated', jest.fn());
    const unsubscribeThree = subscribeToOperationsEvent('snapshot', jest.fn());

    expect(global.EventSource).toHaveBeenCalledTimes(1);
    expect(addEventListener).toHaveBeenCalledTimes(2);

    unsubscribeOne();
    unsubscribeTwo();
    unsubscribeThree();
    expect(close).toHaveBeenCalledTimes(1);
  });
});
