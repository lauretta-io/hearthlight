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
    return JSON.stringify(await response.json());
  }
  return '';
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
