import { KilaSifenConnectionError, KilaSifenError } from "./errors";
import type {
  ApiErrorEnvelope,
  ApiSuccess,
  KilaResponse,
  RequestOptions,
} from "./types";

export interface HttpClientOptions {
  apiKey: string;
  baseUrl: string;
  fetch?: typeof globalThis.fetch;
  timeoutMs?: number;
}

interface JsonRequestOptions extends RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  idempotencyKey?: string;
}

export class HttpClient {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly fetchImplementation: typeof globalThis.fetch;
  private readonly timeoutMs: number;

  constructor(options: HttpClientOptions) {
    if (!options.apiKey.trim()) {
      throw new TypeError("apiKey must not be empty");
    }
    if (!options.baseUrl.trim()) {
      throw new TypeError("baseUrl must not be empty");
    }
    const fetchImplementation = options.fetch ?? globalThis.fetch;
    if (!fetchImplementation) {
      throw new TypeError("A Fetch API implementation is required");
    }
    this.apiKey = options.apiKey;
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.fetchImplementation = fetchImplementation;
    this.timeoutMs = options.timeoutMs ?? 30_000;
  }

  async json<T>(path: string, options: JsonRequestOptions = {}): Promise<KilaResponse<T>> {
    const timeout = createTimeout(options.timeoutMs ?? this.timeoutMs, options.signal);
    const headers = new Headers(options.headers);
    headers.set("Accept", "application/json");
    headers.set("X-API-Key", this.apiKey);
    if (options.body !== undefined) {
      headers.set("Content-Type", "application/json");
    }
    if (options.idempotencyKey) {
      headers.set("Idempotency-Key", options.idempotencyKey);
    }

    let response: Response;
    try {
      response = await this.fetchImplementation(`${this.baseUrl}${path}`, {
        method: options.method ?? "GET",
        headers,
        signal: timeout.signal,
        ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
      });
    } catch (error) {
      if (timeout.didTimeout()) {
        throw new KilaSifenConnectionError(
          "sdk.timeout",
          `KilaSifen request timed out after ${options.timeoutMs ?? this.timeoutMs}ms`,
          { cause: error },
        );
      }
      throw new KilaSifenConnectionError(
        "sdk.connection_error",
        "Could not connect to KilaSifen",
        { cause: error },
      );
    } finally {
      timeout.dispose();
    }

    const payload = await parseJson(response);
    if (!response.ok) {
      if (isErrorEnvelope(payload)) {
        throw new KilaSifenError(payload.error, response.status);
      }
      throw new KilaSifenConnectionError(
        "sdk.invalid_response",
        `KilaSifen returned HTTP ${response.status} without a valid error envelope`,
      );
    }
    if (!isSuccessEnvelope<T>(payload)) {
      throw new KilaSifenConnectionError(
        "sdk.invalid_response",
        "KilaSifen returned an invalid success envelope",
      );
    }
    return {
      data: payload.data,
      correlationId: payload.correlation_id,
      status: response.status,
    };
  }
}

async function parseJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch (error) {
    throw new KilaSifenConnectionError(
      "sdk.invalid_response",
      `KilaSifen returned a non-JSON response with HTTP ${response.status}`,
      { cause: error },
    );
  }
}

function isSuccessEnvelope<T>(value: unknown): value is ApiSuccess<T> {
  return isRecord(value) && "data" in value && typeof value.correlation_id === "string";
}

function isErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (!isRecord(value) || !isRecord(value.error)) return false;
  return (
    typeof value.error.code === "string" &&
    typeof value.error.message === "string" &&
    typeof value.error.category === "string" &&
    typeof value.error.correlation_id === "string"
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function createTimeout(timeoutMs: number, callerSignal?: AbortSignal): {
  signal: AbortSignal;
  didTimeout: () => boolean;
  dispose: () => void;
} {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new RangeError("timeoutMs must be a positive finite number");
  }
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const abortFromCaller = () => controller.abort(callerSignal?.reason);
  callerSignal?.addEventListener("abort", abortFromCaller, { once: true });
  if (callerSignal?.aborted) abortFromCaller();

  return {
    signal: controller.signal,
    didTimeout: () => timedOut,
    dispose: () => {
      clearTimeout(timer);
      callerSignal?.removeEventListener("abort", abortFromCaller);
    },
  };
}
