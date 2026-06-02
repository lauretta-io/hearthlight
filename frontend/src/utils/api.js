export const fetchWithTimeout = (url, options = {}, timeoutMs = 20000) => (
  fetch(url, {
    ...options,
    signal: typeof AbortSignal.timeout === 'function'
      ? AbortSignal.timeout(timeoutMs)
      : options.signal,
  })
);

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

export const parseApiJson = async (response, fallbackMessage) => {
  const text = await readResponseText(response);
  if (!response.ok) {
    let detail = fallbackMessage;
    try {
      const payload = text ? JSON.parse(text) : {};
      if (typeof payload?.detail === 'string' && payload.detail.trim()) {
        detail = payload.detail;
      }
    } catch (error) {
      if (text?.trim()) {
        detail = `${fallbackMessage} (${text.trim().slice(0, 120)})`;
      }
    }
    throw new Error(detail);
  }
  try {
    return text ? JSON.parse(text) : {};
  } catch (error) {
    throw new Error(
      `${fallbackMessage}: server returned non-JSON (${response.status})`,
    );
  }
};
