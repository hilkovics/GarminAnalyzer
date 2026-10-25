// Thin fetch wrapper over the FastAPI contract (docs/API.md). Types come from schema.d.ts, generated from
// docs/openapi.json by `npm run gen:api` – never edit them by hand.
import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";

import type { components } from "./schema";

export type Schemas = components["schemas"];

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

type Params = Record<string, string | number | boolean | null | undefined>;

export function apiUrl(path: string, params?: Params): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== null && value !== undefined && value !== "") query.set(key, String(value));
  }
  const qs = query.toString();
  return `/api${path}${qs ? `?${qs}` : ""}`;
}

/** GET/POST/PUT JSON; a non-2xx answer becomes an ApiError carrying the service's message (`detail`). */
export async function api<T>(path: string, init?: RequestInit & { params?: Params }): Promise<T> {
  const { params, ...rest } = init ?? {};
  const response = await fetch(apiUrl(path, params), {
    ...rest,
    headers: { "Content-Type": "application/json", Accept: "application/json", ...(rest.headers ?? {}) },
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") message = body.detail;
      else if (Array.isArray(body?.detail)) message = body.detail.map((d: { msg?: string }) => d.msg).join("; ");
    } catch {
      // not JSON – keep the status text
    }
    throw new ApiError(response.status, message);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

/** A GET endpoint as a TanStack query; the key is the path plus its params. */
export function useApi<T>(path: string, params?: Params, options?: { enabled?: boolean; keepPrevious?: boolean }) {
  return useQuery<T, ApiError>({
    queryKey: [path, params ?? {}] as QueryKey,
    queryFn: () => api<T>(path, { params }),
    enabled: options?.enabled ?? true,
    placeholderData: options?.keepPrevious ? keepPreviousData : undefined,
  });
}

/** A POST/PUT endpoint; on success every query is refreshed (the server recomputes plans, loads, …). */
export function useApiMutation<TBody, TResult>(method: "POST" | "PUT", path: (body: TBody) => string) {
  const client = useQueryClient();
  return useMutation<TResult, ApiError, TBody>({
    mutationFn: (body) => api<TResult>(path(body), { method, body: JSON.stringify(stripPath(body)) }),
    onSuccess: () => client.invalidateQueries(),
  });
}

/** Mutation bodies may carry routing fields prefixed with "_" (e.g. `_id`); they never go into the JSON. */
function stripPath<T>(body: T): unknown {
  if (body === null || typeof body !== "object" || Array.isArray(body)) return body;
  return Object.fromEntries(Object.entries(body as Record<string, unknown>).filter(([k]) => !k.startsWith("_")));
}
