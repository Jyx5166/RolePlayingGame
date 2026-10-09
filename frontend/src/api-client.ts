export interface ApiErrorBody {
  code?: string;
  message?: string;
  request_id?: string;
  details?: unknown;
  detail?: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string;
  readonly details: unknown;
  readonly body: ApiErrorBody;

  constructor(status: number, body: ApiErrorBody) {
    const requestId = typeof body.request_id === "string" ? body.request_id : "";
    const detail = typeof body.detail === "string" ? body.detail : "";
    const message = body.message || detail || "请求失败";
    super(`${message}${requestId ? `（请求 ${requestId}）` : ""}`);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code || `HTTP_${status}`;
    this.requestId = requestId;
    this.details = body.details;
    this.body = body;
  }
}

export function normalizeApiPath(path: string): string {
  if (path.startsWith("/api/") && !path.startsWith("/api/v1/")) {
    return path.replace("/api/", "/api/v1/");
  }
  return path;
}

interface ApiClientOptions {
  fetchImpl?: typeof fetch;
  getCsrfToken: () => string;
  onUnauthorized?: (requestPath: string) => void;
}

export function createApiClient({
  fetchImpl = fetch,
  getCsrfToken,
  onUnauthorized,
}: ApiClientOptions) {
  return {
    async request<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
      const requestPath = normalizeApiPath(path);
      const headers = new Headers(options.headers);
      if (options.body && !headers.has("Content-Type")) {
        headers.set("Content-Type", "application/json");
      }
      const method = (options.method || "GET").toUpperCase();
      const csrfToken = getCsrfToken();
      if (!["GET", "HEAD", "OPTIONS"].includes(method) && csrfToken) {
        headers.set("X-CSRF-Token", csrfToken);
      }
      const response = await fetchImpl(requestPath, {
        ...options,
        headers,
        credentials: "same-origin",
      });
      const data = await response.json().catch(() => ({})) as T & ApiErrorBody;
      if (!response.ok) {
        if (response.status === 401) onUnauthorized?.(requestPath);
        throw new ApiError(response.status, data);
      }
      return data;
    },
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
