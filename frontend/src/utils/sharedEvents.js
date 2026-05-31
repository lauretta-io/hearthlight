import { BaseURL } from '../config';

let sharedEventSource = null;
const subscribersByEvent = new Map();

const getSubscriberCount = () => (
  Array.from(subscribersByEvent.values()).reduce(
    (total, subscribers) => total + subscribers.size,
    0,
  )
);

const ensureEventSource = () => {
  if (sharedEventSource || typeof EventSource === 'undefined') {
    return sharedEventSource;
  }
  sharedEventSource = new EventSource(`${BaseURL}/operations/events`);
  sharedEventSource.onerror = () => {};
  return sharedEventSource;
};

export const subscribeToOperationsEvent = (eventName, callback) => {
  if (typeof callback !== 'function') {
    return () => {};
  }
  const source = ensureEventSource();
  if (!source) {
    return () => {};
  }
  if (!subscribersByEvent.has(eventName)) {
    subscribersByEvent.set(eventName, new Set());
    source.addEventListener(eventName, (event) => {
      const listeners = subscribersByEvent.get(eventName);
      if (!listeners) {
        return;
      }
      listeners.forEach((listener) => listener(event));
    });
  }
  subscribersByEvent.get(eventName).add(callback);
  return () => {
    const listeners = subscribersByEvent.get(eventName);
    if (!listeners) {
      return;
    }
    listeners.delete(callback);
    if (listeners.size === 0) {
      subscribersByEvent.delete(eventName);
    }
    if (getSubscriberCount() === 0 && sharedEventSource) {
      sharedEventSource.close();
      sharedEventSource = null;
    }
  };
};
