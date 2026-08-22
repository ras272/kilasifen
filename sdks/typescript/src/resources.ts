import { HttpClient } from "./http";
import type {
  CreateOptions,
  CreatedDocument,
  DocumentWithJob,
  FacturaCreateInput,
  Job,
  KilaResponse,
  NotaCreditoCreateInput,
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
        ...requestFields(options),
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
        ...requestFields(options),
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

function segment(value: string, name: string): string {
  if (!value.trim()) throw new TypeError(`${name} must not be empty`);
  return encodeURIComponent(value);
}
