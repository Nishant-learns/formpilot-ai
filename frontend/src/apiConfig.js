/**
 * Centralized API and WebSocket configuration for FormPilot.
 * Supports unified local hosting, container deployment, and Vercel cloud deployments.
 *
 * The session token is kept in localStorage so a refresh keeps the candidate
 * signed in, and it is attached to every API request and WebSocket URL.  It is
 * never placed in a URL that is logged as a page navigation.
 */

export const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '');

export const PRACTICE_PORTAL_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_PRACTICE_PORTAL_URL)
  || 'https://gov-portal-simulator.vercel.app';

const SESSION_KEY = 'formpilot.session.v1';

/** Fired when the backend rejects a stored session (expired or wiped). */
export const SESSION_EXPIRED_EVENT = 'formpilot:session-expired';

export function getSessionToken() {
  if (typeof window === 'undefined') return '';
  try {
    return window.localStorage.getItem(SESSION_KEY) || '';
  } catch {
    return '';
  }
}

export function setSessionToken(token) {
  if (typeof window === 'undefined') return;
  try {
    if (token) window.localStorage.setItem(SESSION_KEY, token);
    else window.localStorage.removeItem(SESSION_KEY);
  } catch {
    /* private mode: the in-memory token still works for this tab */
  }
}

export function clearSessionToken() {
  setSessionToken('');
}

function isApiRequest(url) {
  if (typeof url !== 'string') return false;
  if (url.startsWith('/api/') || url.startsWith('/uploads/')) return true;
  if (API_BASE && (url === API_BASE || url.startsWith(`${API_BASE}/`))) return true;
  return false;
}

// Seamless fetch interceptor: prefix relative API & upload endpoints when
// API_BASE is configured (e.g. Vercel frontend calling a Render/Railway API),
// and attach the account session token to every API call.
if (typeof window !== 'undefined') {
  const originalFetch = window.fetch;
  window.fetch = function (input, init) {
    let target = input;

    if (typeof target === 'string' && API_BASE) {
      if (target.startsWith('/api/') || target.startsWith('/uploads/')) {
        target = `${API_BASE}${target}`;
      }
    }

    const token = getSessionToken();
    if (!token || !isApiRequest(target)) {
      return originalFetch.call(this, target, init);
    }

    const nextInit = { ...(init || {}) };
    const headers = new Headers(nextInit.headers || (typeof input === 'string' ? undefined : input.headers));
    if (!headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${token}`);
    }
    nextInit.headers = headers;

    return originalFetch.call(this, target, nextInit).then((response) => {
      // A stored token that the backend no longer accepts means the account
      // was removed or the session expired.  Clear it once and let the app
      // return to the sign-in screen instead of leaving every panel empty.
      if (response.status === 401 && isApiRequest(target) && getSessionToken()) {
        clearSessionToken();
        try {
          window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT));
        } catch {
          /* older browsers: the cleared token still stops the retry loop */
        }
      }
      return response;
    });
  };
}

export function apiUrl(endpoint) {
  const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  return `${API_BASE}${cleanEndpoint}`;
}

function withToken(url) {
  const token = getSessionToken();
  if (!token) return url;
  return `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`;
}

export function getWsUrl(path) {
  if (!path) return '';
  if (path.startsWith('ws://') || path.startsWith('wss://')) return withToken(path);

  const cleanPath = path.startsWith('/') ? path : `/${path}`;

  if (API_BASE) {
    const wsProtocol = API_BASE.startsWith('https://') ? 'wss:' : 'ws:';
    const host = API_BASE.replace(/^https?:\/\//, '');
    return withToken(`${wsProtocol}//${host}${cleanPath}`);
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return withToken(`${protocol}//${window.location.host}${cleanPath}`);
}
