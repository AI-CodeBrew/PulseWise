// The ONLY place the frontend talks to the backend.
// The browser never talks to PostHog directly; PostHog keys live in the backend only.
//
// Login uses an httpOnly cookie set by the backend. `credentials: "include"` makes
// the browser send that cookie with every request (JavaScript itself can't read it).

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

export type QueryParams = Record<string, string | number | null | undefined>;

/** An error with a message that is safe and friendly to show on screen. */
export class ApiError extends Error {
  constructor(
    public status: number, // 0 = could not reach the server at all
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// When any request answers 401 ("not logged in / session expired"), tell the
// AuthProvider so it can send the user to the login page.
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

interface RequestOptions {
  params?: QueryParams;
  body?: unknown;
  signal?: AbortSignal;
  /** Don't treat a 401 as "logged out" (e.g. the login form itself: 401 = wrong password). */
  quiet401?: boolean;
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

async function request<T>(method: Method, path: string, options: RequestOptions = {}): Promise<T> {
  const url = new URL(API_URL + path);
  for (const [key, value] of Object.entries(options.params ?? {})) {
    if (value !== null && value !== undefined && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      signal: options.signal,
      cache: "no-store",
      credentials: "include",
      headers: options.body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    });
  } catch (err) {
    if (options.signal?.aborted) throw err; // cancelled on purpose, not a real error
    throw new ApiError(0, "Can't reach the server. Please check your connection and try again.");
  }

  if (!response.ok) {
    if (response.status === 401 && !options.quiet401) onUnauthorized?.();
    throw new ApiError(response.status, await readErrorMessage(response));
  }
  return (await response.json()) as T;
}

/** GET a backend endpoint and return its JSON. Throws ApiError on failure. */
export function apiGet<T>(path: string, params?: QueryParams, signal?: AbortSignal): Promise<T> {
  return request<T>("GET", path, { params, signal });
}

/** POST JSON to a backend endpoint. Throws ApiError on failure. */
export function apiPost<T>(path: string, body: unknown = {}, options: { quiet401?: boolean } = {}): Promise<T> {
  return request<T>("POST", path, { body, quiet401: options.quiet401 });
}

/** PUT JSON (create or replace). */
export function apiPut<T>(path: string, body: unknown): Promise<T> {
  return request<T>("PUT", path, { body });
}

/** PATCH (partial update) JSON. */
export function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return request<T>("PATCH", path, { body });
}

/** DELETE, with a JSON body (the admin API asks you to type the name to confirm deletions). */
export function apiDelete<T>(path: string, body: unknown = {}): Promise<T> {
  return request<T>("DELETE", path, { body });
}

/** The backend sends errors as {"detail": "..."} (or a list, for validation errors). */
async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return "Please check the form: " + body.detail.map((d: { msg?: string }) => d.msg).join("; ");
    }
  } catch {
    // body was not JSON; fall through to the generic message
  }
  if (response.status === 404) return "Not found.";
  return `Something went wrong (error ${response.status}). Please try again.`;
}
