export class ApiError extends Error {
  status: number;
  body?: unknown;
  constructor(message: string, status: number, body?: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

/**
 * If you want to hard-point frontend to backend, set in .env:
 * VITE_API_BASE=http://localhost:8000
 *
 * If you use Vite proxy for /api, you can keep it empty ("") and it still works.
 */
export const API_BASE: string = (import.meta as any).env?.VITE_API_BASE ?? "";

export function apiUrl(path: string): string {
  if (!path) return API_BASE || "";
  if (path.startsWith("http://") || path.startsWith("https://")) return path;

  const p = path.startsWith("/") ? path : `/${path}`;
  return API_BASE ? `${API_BASE}${p}` : p;
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
  });

  const text = await res.text();
  const data = text ? safeJson(text) : null;

  if (!res.ok) {
    throw new ApiError(`GET ${path} failed`, res.status, data);
  }
  return data as T;
}

function safeJson(text: string) {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
