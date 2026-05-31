const pollers = new Map();

const createPoller = (key, intervalMs) => {
  const subscribers = new Set();
  let timerId = null;

  const tick = () => {
    subscribers.forEach((subscriber) => {
      subscriber();
    });
  };

  return {
    key,
    intervalMs,
    subscribers,
    start() {
      if (timerId !== null) {
        return;
      }
      timerId = window.setInterval(tick, intervalMs);
    },
    stop() {
      if (timerId !== null) {
        window.clearInterval(timerId);
        timerId = null;
      }
    },
  };
};

export const subscribeToSharedPoll = (key, intervalMs, callback, { runImmediately = false } = {}) => {
  if (typeof callback !== 'function') {
    return () => {};
  }
  let poller = pollers.get(key);
  if (!poller) {
    poller = createPoller(key, intervalMs);
    pollers.set(key, poller);
  }
  poller.subscribers.add(callback);
  poller.start();
  if (runImmediately) {
    callback();
  }
  return () => {
    const current = pollers.get(key);
    if (!current) {
      return;
    }
    current.subscribers.delete(callback);
    if (current.subscribers.size === 0) {
      current.stop();
      pollers.delete(key);
    }
  };
};

