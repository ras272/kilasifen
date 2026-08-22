import { HttpClient } from "./http";
import type {
  CreateOptions,
  CreatedDocument,
  DocumentWithJob,
  FacturaCreateInput,
  Job,
  KilaResponse,
  NotaCreditoCreateInput,
  NotaDebitoCreateInput,
  ReconciledDocument,
  RequestOptions,
} from "./types";

export class FacturasResource {
  constructor(private readonly http: HttpClient) {}

  create(
    emitterId: string,
    input: FacturaCreateInput,
    options: CreateOptions = {},
  ): Promise<KilaResponse<CreatedDocument>> {
    const idempotencyKey = options.idempotencyKey;
    return this.http.json<CreatedDocument>(
      `/v1/emitters/${segment(emitterId, "emitterId")}/documents/facturas`,
      {
        method: "POST",
        body: idempotencyKey
          ? { ...input, idempotency_key: idempotencyKey }
          : input,
        ...(idempotencyKey ? { idempotencyKey } : {}),
        ...createRequestFields(options),
      },
    );
  }
}

export class NotasCreditoResource {
  constructor(private readonly http: HttpClient) {}

  create(
    emitterId: string,
    input: NotaCreditoCreateInput,
    options: CreateOptions = {},
  ): Promise<KilaResponse<CreatedDocument>> {
    const idempotencyKey = options.idempotencyKey;
    return this.http.json<CreatedDocument>(
      `/v1/emitters/${segment(emitterId, "emitterId")}/documents/notas-credito`,
      {
        method: "POST",
        body: idempotencyKey
          ? { ...input, idempotency_key: idempotencyKey }
          : input,
        ...(idempotencyKey ? { idempotencyKey } : {}),
        ...createRequestFields(options),
      },
    );
  }
}

export class NotasDebitoResource {
  constructor(private readonly http: HttpClient) {}

  create(
    emitterId: string,
    input: NotaDebitoCreateInput,
    options: CreateOptions = {},
  ): Promise<KilaResponse<CreatedDocument>> {
    const idempotencyKey = options.idempotencyKey;
    return this.http.json<CreatedDocument>(
      `/v1/emitters/${segment(emitterId, "emitterId")}/documents/notas-debito`,
      {
        method: "POST",
        body: idempotencyKey
          ? { ...input, idempotency_key: idempotencyKey }
          : input,
        ...(idempotencyKey ? { idempotencyKey } : {}),
        ...createRequestFields(options),
      },
    );
  }
}

export class DocumentsResource {
  constructor(private readonly http: HttpClient) {}

  get(
    emitterId: string,
    documentId: string,
    options: RequestOptions = {},
  ): Promise<KilaResponse<DocumentWithJob>> {
    return this.http.json<DocumentWithJob>(
      `/v1/emitters/${segment(emitterId, "emitterId")}/documents/${segment(documentId, "documentId")}`,
      requestFields(options),
    );
  }

  /**
   * Resolve an uncertain document by querying SIFEN with its existing CDC.
   * This operation never resubmits the fiscal document.
   */
  reconcile(
    emitterId: string,
    documentId: string,
    options: RequestOptions = {},
  ): Promise<KilaResponse<ReconciledDocument>> {
    return this.http.json<ReconciledDocument>(
      `/v1/emitters/${segment(emitterId, "emitterId")}/queries/documents/${segment(documentId, "documentId")}/reconcile`,
      { method: "POST", ...requestFields(options) },
    );
  }
}

export class JobsResource {
  constructor(private readonly http: HttpClient) {}

  get(
    emitterId: string,
    jobId: string,
    options: RequestOptions = {},
  ): Promise<KilaResponse<{ job: Job }>> {
    return this.http.json<{ job: Job }>(
      `/v1/emitters/${segment(emitterId, "emitterId")}/jobs/${segment(jobId, "jobId")}`,
      requestFields(options),
    );
  }
}

function requestFields(options: RequestOptions): RequestOptions {
  return {
    ...(options.signal ? { signal: options.signal } : {}),
    ...(options.timeoutMs === undefined ? {} : { timeoutMs: options.timeoutMs }),
    ...(options.headers ? { headers: options.headers } : {}),
  };
}

function createRequestFields(options: CreateOptions): RequestOptions {
  const headers = { ...options.headers };
  const reservedHeader = Object.keys(headers).find(
    (name) => name.toLowerCase() === "x-kila-test-outcome",
  );
  if (reservedHeader) {
    throw new TypeError(
      "Use sandboxOutcome instead of setting X-Kila-Test-Outcome directly",
    );
  }
  if (options.sandboxOutcome !== undefined) {
    if (!isSandboxOutcome(options.sandboxOutcome)) {
      throw new TypeError(
        "sandboxOutcome must be approved, approved_with_observation, or rejected",
      );
    }
    headers["X-Kila-Test-Outcome"] = options.sandboxOutcome;
  }
  return {
    ...(options.signal ? { signal: options.signal } : {}),
    ...(options.timeoutMs === undefined ? {} : { timeoutMs: options.timeoutMs }),
    ...(Object.keys(headers).length > 0 ? { headers } : {}),
  };
}

function isSandboxOutcome(value: string): boolean {
  return value === "approved" ||
    value === "approved_with_observation" ||
    value === "rejected";
}

function segment(value: string, name: string): string {
  if (!value.trim()) throw new TypeError(`${name} must not be empty`);
  return encodeURIComponent(value);
}
