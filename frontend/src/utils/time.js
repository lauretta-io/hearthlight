export const formatDateTime = (dateTimeString) => {

  if (!dateTimeString) {
    return '';
  }

  const utcDateTimeString = dateTimeString.endsWith('Z') || dateTimeString.includes('+')
    ? dateTimeString
    : dateTimeString + 'Z';

  const options = {
    hour: 'numeric',
    minute: 'numeric',
    hour12: true,
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  };

  const utcDate = new Date(utcDateTimeString);
  return utcDate.toLocaleString('en-US', options);
};

export const formatSecondsAgo = (seconds) => {
  if (seconds === null || seconds === undefined) {
    return '';
  }
  if (seconds < 60) {
    return `${seconds}s ago`;
  }
  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}m ago`;
  }
  if (seconds < 86400) {
    return `${Math.floor(seconds / 3600)}h ago`;
  }
  return `${Math.floor(seconds / 86400)}d ago`;
};

export const secondsSinceDateTime = (dateTimeString, now = Date.now()) => {
  if (!dateTimeString) {
    return null;
  }
  const utcDateTimeString = dateTimeString.endsWith('Z') || dateTimeString.includes('+')
    ? dateTimeString
    : `${dateTimeString}Z`;
  const timestamp = Date.parse(utcDateTimeString);
  if (Number.isNaN(timestamp)) {
    return null;
  }
  return Math.max(0, Math.floor((now - timestamp) / 1000));
};
