import type { ApiErrorPayload } from "./types";

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
    this.retryable = status === 408 || status === 425 || status === 429 || status >= 500;
  }
}

export class KilaSifenConnectionError extends Error {
  readonly code: "sdk.timeout" | "sdk.connection_error" | "sdk.invalid_response";
  readonly retryable: boolean;

  constructor(
    code: KilaSifenConnectionError["code"],
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "KilaSifenConnectionError";
    this.code = code;
    this.retryable = code !== "sdk.invalid_response";
  }
}

export function isKilaSifenError(error: unknown): error is KilaSifenError {
  return error instanceof KilaSifenError;
}
