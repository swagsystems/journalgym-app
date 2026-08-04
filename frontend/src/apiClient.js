export const API = '/api';

const API_TIMEOUT_MS = 15000;

export async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  let res;
  try {
    res = await fetch(`${API}${path}`, {
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
      signal: controller.signal,
    });
  } catch (error) {
    if (error?.name === 'AbortError') {
      const timeoutError = new Error('Request timed out. Check the connection and try again.');
      timeoutError.status = 0;
      throw timeoutError;
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
  if (!res.ok) {
    let detail = await res.text();
    try {
      detail = formatApiErrorDetail(JSON.parse(detail).detail || detail);
    } catch {
      // Response was already plain text.
    }
    const error = new Error(detail || res.statusText);
    error.status = res.status;
    throw error;
  }
  return res.json();
}

function formatApiErrorDetail(detail) {
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      const location = Array.isArray(item?.loc) ? item.loc.filter((part) => part !== 'body').join('.') : '';
      const message = item?.msg || JSON.stringify(item);
      return location ? `${location}: ${message}` : message;
    }).join('; ');
  }
  if (detail && typeof detail === 'object') return detail.message || detail.detail || JSON.stringify(detail);
  return detail;
}
