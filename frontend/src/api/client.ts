/**
 * Thin fetch wrapper matching the backend's structured error contract
 * ({code, message, request_id} — see backend/app/core/errors.py). Every page-level data hook
 * is expected to go through this rather than calling fetch() directly, so error handling and
 * the API base path stay in one place.
 *
 * Base URL resolution: local dev leaves VITE_API_BASE_URL unset, so requests go to relative
 * "/api/..." paths, proxied to the backend by vite.config.ts's dev-server proxy. A Render (or
 * any split-origin) deployment sets VITE_API_BASE_URL to the backend service's hostname at
 * build time — see render.yaml — and every request is sent there directly instead.
 */

const RAW_BASE = import.meta.env.VITE_API_BASE_URL?.trim();
const API_BASE = RAW_BASE ? `https://${RAW_BASE.replace(/^https?:\/\//, "")}` : "";

export interface ApiError {
  code: string;
  message: string;
  request_id: string;
}

export class ApiRequestError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: ApiError,
  ) {
    super(body.message);
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}/api${path}`);
  if (!response.ok) {
    throw new ApiRequestError(response.status, await response.json());
  }
  return response.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    throw new ApiRequestError(response.status, await response.json());
  }
  return response.json() as Promise<T>;
}
