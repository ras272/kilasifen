import type { ApiErrorPayload } from "./types";

/**
 * HTTP statuses that are safe to retry with backoff (reusing the same
 * idempotency key for fiscal mutations).
 */
export function isRetryableStatus(status: number): boolean {
  return status === 408 || status === 425 || status === 429 || status >= 500;
}

export class KilaSifenError extends Error {
  readonly status: number;
  readonly code: string;
  readonly category: string;
  readonly correlationId: string | null;
  readonly details: Record<string, unknown> | null;
  readonly retryable: boolean;

  constructor(payload: ApiErrorPayload, status: number, options?: ErrorOptions) {
    super(payload.message, options);
    this.name = "KilaSifenError";
    this.status = status;
    this.code = payload.code;
    this.category = payload.category;
    this.correlationId = payload.correlation_id || null;
    this.details = payload.details ?? null;
    this.retryable = isRetryableStatus(status);
  }
}

export type KilaSifenConnectionErrorCode =
  | "sdk.timeout"
  | "sdk.connection_error"
  | "sdk.invalid_response"
  | "sdk.http_error";

export interface KilaSifenConnectionErrorOptions extends ErrorOptions {
  /** HTTP status, present when the server answered (`sdk.http_error`). */
  status?: number;
  /** Value of the `X-Correlation-ID` response header, when present. */
  correlationId?: string | null;
}

/**
 * Transport-level failure: timeout, network error, a malformed success body
 * (`sdk.invalid_response`) or an HTTP error without the KilaSifen error
 * envelope (`sdk.http_error`, for example a proxy `502` HTML page).
 */
export class KilaSifenConnectionError extends Error {
  readonly code: KilaSifenConnectionErrorCode;
  readonly status: number | null;
  readonly correlationId: string | null;
  readonly retryable: boolean;

  constructor(
    code: KilaSifenConnectionErrorCode,
    message: string,
    options: KilaSifenConnectionErrorOptions = {},
  ) {
    const { status, correlationId, ...errorOptions } = options;
    super(message, errorOptions);
    this.name = "KilaSifenConnectionError";
    this.code = code;
    this.status = status ?? null;
    this.correlationId = correlationId || null;
    this.retryable = connectionErrorIsRetryable(code, this.status);
  }
}

export function isKilaSifenError(error: unknown): error is KilaSifenError {
  return error instanceof KilaSifenError;
}

function connectionErrorIsRetryable(
  code: KilaSifenConnectionErrorCode,
  status: number | null,
): boolean {
  if (code === "sdk.http_error") return status !== null && isRetryableStatus(status);
  return code !== "sdk.invalid_response";
}
