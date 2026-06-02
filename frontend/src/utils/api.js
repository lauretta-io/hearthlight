export const fetchWithTimeout = (url, options = {}, timeoutMs = 20000) => (
  fetch(url, {
    ...options,
    signal: typeof AbortSignal.timeout === 'function'
      ? AbortSignal.timeout(timeoutMs)
      : options.signal,
  })
);

export const readApiPayload = async (response, fallbackMessage) => {
  const text = await readResponseText(response);
  try {
    return text ? JSON.parse(text) : {};
  } catch (error) {
    throw new Error(
      `${fallbackMessage}: server returned non-JSON (${response.status})`,
    );
  }
};

const readResponseText = async (response) => {
  if (typeof response.text === 'function') {
    return response.text();
  }
  if (typeof response.json === 'function') {
    try {
      return JSON.stringify(await response.json());
    } catch (error) {
      return '';
    }
  }
  return '';
};

export const formatApiError = (error, fallbackMessage) => {
  const message = error?.message || '';
  if (
    error instanceof SyntaxError
    || /Unexpected token/i.test(message)
    || /is not valid JSON/i.test(message)
  ) {
    return fallbackMessage;
  }
  return message || fallbackMessage;
};

export const fetchJson = async (
  url,
  options = {},
  fallbackMessage,
  timeoutMs = 20000,
) => {
  const response = await fetchWithTimeout(url, options, timeoutMs);
  return parseApiJson(response, fallbackMessage);
};

export const parseApiJson = async (response, fallbackMessage) => {
  const payload = await readApiPayload(response, fallbackMessage);
  if (!response.ok) {
    let detail = fallbackMessage;
    if (typeof payload?.detail === 'string' && payload.detail.trim()) {
      detail = payload.detail;
    }
    throw new Error(detail);
  }
  return payload;
};
