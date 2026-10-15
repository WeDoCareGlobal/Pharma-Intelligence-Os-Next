/**
 * Local stand-in for the platform SDK's `@appdeploy/client`.
 *
 * The deployed app runs on the appdeploy platform, which injects `@appdeploy/client`
 * at build time. That package is not published to npm (verified: `npm view
 * @appdeploy/client` -> 404), so CI, GitHub Pages and any local `npm run build`
 * cannot resolve it. This module implements the same two-call surface the app
 * uses — `api.get/post` and `ws.connect` — over plain fetch + WebSocket, so the
 * repository builds, tests and deploys standalone.
 *
 * Vite aliases `@appdeploy/client` here (see vite.config.ts). When the platform
 * provides the real package it takes precedence via the alias order.
 */

type Query = Record<string, string | number | boolean | undefined | null>;

export interface ApiResponse<T = unknown> {
  data: T;
  status: number;
  ok: boolean;
}

const BASE = (import.meta.env?.VITE_API_BASE ?? '').replace(/\/$/, '');

function buildUrl(path: string, query?: Query): string {
  const url = `${BASE}${path.startsWith('/') ? path : `/${path}`}`;
  if (!query) return url;
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null) qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `${url}?${s}` : url;
}

async function request<T>(
  method: 'GET' | 'POST',
  path: string,
  body?: unknown,
  query?: Query,
): Promise<ApiResponse<T>> {
  const res = await fetch(buildUrl(path, query), {
    method,
    headers: body === undefined ? undefined : { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const detail =
      data && typeof data === 'object' && 'message' in (data as Record<string, unknown>)
        ? String((data as Record<string, unknown>).message)
        : `HTTP ${res.status}`;
    throw new Error(detail);
  }
  return { data: data as T, status: res.status, ok: res.ok };
}

/**
 * The platform SDK handed back untyped JSON payloads and the existing call sites
 * rely on that, so the default type parameter stays permissive. Call sites that
 * want a checked shape pass their own generic (see `loadApprovals` in App.tsx).
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyPayload = any;

export const api = {
  get: <T = AnyPayload>(path: string, query?: Query) => request<T>('GET', path, undefined, query),
  post: <T = AnyPayload>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T = AnyPayload>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  del: <T = AnyPayload>(path: string) => request<T>('GET', path),
};

export interface RealtimeMessage {
  type?: string;
  payload?: Record<string, unknown>;
  [k: string]: unknown;
}

export interface RealtimeConnection {
  readonly connectionId: string | null;
  readonly ready: Promise<void>;
  onMessage(handler: (message: RealtimeMessage) => void): void;
  send(payload: unknown): void;
  disconnect(): void;
}

/**
 * Realtime transport. Uses a native WebSocket when the host exposes one, and
 * degrades to an inert connection otherwise so the UI can still render its
 * "waiting for backend" state instead of throwing during mount.
 */
export function connect(): RealtimeConnection {
  const handlers: Array<(m: RealtimeMessage) => void> = [];
  const proto = typeof location !== 'undefined' && location.protocol === 'https:' ? 'wss' : 'ws';
  const host = typeof location !== 'undefined' ? location.host : 'localhost';
  const url = `${BASE || ''}${proto}://${host}/api/realtime`;

  let socket: WebSocket | null = null;
  let connectionId: string | null = null;

  const ready = new Promise<void>((resolve) => {
    if (typeof WebSocket === 'undefined') {
      resolve();
      return;
    }
    try {
      socket = new WebSocket(url);
    } catch {
      resolve();
      return;
    }
    socket.onopen = () => resolve();
    socket.onerror = () => resolve();
    socket.onclose = () => resolve();
    socket.onmessage = (ev) => {
      try {
        const msg = JSON.parse(String(ev.data)) as RealtimeMessage;
        if (msg.type === 'system.connected') {
          connectionId = String(msg.payload?.connection_id ?? '') || null;
        }
        handlers.forEach((h) => h(msg));
      } catch {
        /* ignore malformed frames */
      }
    };
  });

  return {
    get connectionId() {
      return connectionId;
    },
    ready,
    onMessage(handler) {
      handlers.push(handler);
    },
    send(payload) {
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(payload));
      }
    },
    disconnect() {
      handlers.length = 0;
      try {
        socket?.close();
      } catch {
        /* already closed */
      }
    },
  };
}

export const ws = { connect };

export default { api, ws };
