import { HttpClient } from "./http";
import type {
  CancelDocumentInput,
  CreateOptions,
  CreatedDocument,
  CreatedEvent,
  CreatedInutilization,
  DocumentList,
  DocumentListOptions,
  DocumentWithJob,
  EventWithJob,
  FacturaCreateInput,
  InutilizeNumbersInput,
  Job,
  KilaResponse,
  NotaCreditoCreateInput,
  NotaDebitoCreateInput,
  ReconciledDocument,
  RequestOptions,
  RucQuery,
  WebhookDelivery,
  WebhookEndpoint,
  WebhookEndpointCreateInput,
  WebhookEndpointUpdateInput,
  WebhookReplayInput,
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

  list(
    emitterId: string,
    options: DocumentListOptions = {},
  ): Promise<KilaResponse<DocumentList>> {
    const query = queryString({
      limit: options.limit,
      offset: options.offset,
      internal_status: options.internalStatus,
      document_type: options.documentType,
      external_id: options.externalId,
      cdc: options.cdc,
    });
    return this.http.json<DocumentList>(
      `/v1/emitters/${segment(emitterId, "emitterId")}/documents${query}`,
      requestFields(options),
    );
  }

  query(
    emitterId: string,
    documentId: string,
    options: RequestOptions = {},
  ): Promise<KilaResponse<ReconciledDocument>> {
    return this.http.json<ReconciledDocument>(
      `/v1/emitters/${segment(emitterId, "emitterId")}/queries/documents/${segment(documentId, "documentId")}`,
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

export class QueriesResource {
  constructor(private readonly http: HttpClient) {}

  ruc(
    emitterId: string,
    ruc: string,
    options: RequestOptions = {},
  ): Promise<KilaResponse<{ ruc_query: RucQuery }>> {
    return this.http.json<{ ruc_query: RucQuery }>(
      `/v1/emitters/${segment(emitterId, "emitterId")}/queries/ruc/${segment(ruc, "ruc")}`,
      requestFields(options),
    );
  }
}

export class EventsResource {
  constructor(private readonly http: HttpClient) {}

  cancel(
    emitterId: string,
    documentId: string,
    input: CancelDocumentInput,
    options: RequestOptions = {},
  ): Promise<KilaResponse<CreatedEvent>> {
    return this.http.json<CreatedEvent>(
      `/v1/emitters/${segment(emitterId, "emitterId")}/documents/${segment(documentId, "documentId")}/cancel`,
      { method: "POST", body: input, ...requestFields(options) },
    );
  }

  inutilize(
    emitterId: string,
    input: InutilizeNumbersInput,
    options: RequestOptions = {},
  ): Promise<KilaResponse<CreatedInutilization>> {
    return this.http.json<CreatedInutilization>(
      `/v1/emitters/${segment(emitterId, "emitterId")}/inutilizations`,
      { method: "POST", body: input, ...requestFields(options) },
    );
  }

  get(
    emitterId: string,
    eventId: string,
    options: RequestOptions = {},
  ): Promise<KilaResponse<EventWithJob>> {
    return this.http.json<EventWithJob>(
      `/v1/emitters/${segment(emitterId, "emitterId")}/events/${segment(eventId, "eventId")}`,
      requestFields(options),
    );
  }
}

export class WebhooksResource {
  constructor(private readonly http: HttpClient) {}

  create(
    emitterId: string,
    input: WebhookEndpointCreateInput,
    options: RequestOptions = {},
  ): Promise<KilaResponse<{ webhook_endpoint: WebhookEndpoint }>> {
    return this.http.json<{ webhook_endpoint: WebhookEndpoint }>(
      `/v1/emitters/${segment(emitterId, "emitterId")}/webhooks`,
      { method: "POST", body: input, ...requestFields(options) },
    );
  }

  list(
    emitterId: string,
    options: RequestOptions = {},
  ): Promise<KilaResponse<{ webhook_endpoints: WebhookEndpoint[] }>> {
    return this.http.json<{ webhook_endpoints: WebhookEndpoint[] }>(
      `/v1/emitters/${segment(emitterId, "emitterId")}/webhooks`,
      requestFields(options),
    );
  }

  update(
    emitterId: string,
    endpointId: string,
    input: WebhookEndpointUpdateInput,
    options: RequestOptions = {},
  ): Promise<KilaResponse<{ webhook_endpoint: WebhookEndpoint }>> {
    if (Object.keys(input).length === 0) {
      throw new TypeError("webhook update must contain at least one field");
    }
    return this.http.json<{ webhook_endpoint: WebhookEndpoint }>(
      `/v1/emitters/${segment(emitterId, "emitterId")}/webhooks/${segment(endpointId, "endpointId")}`,
      { method: "PATCH", body: input, ...requestFields(options) },
    );
  }

  replay(
    emitterId: string,
    endpointId: string,
    input: WebhookReplayInput,
    options: RequestOptions = {},
  ): Promise<KilaResponse<{ delivery: WebhookDelivery; job: Job }>> {
    return this.http.json<{ delivery: WebhookDelivery; job: Job }>(
      `/v1/emitters/${segment(emitterId, "emitterId")}/webhooks/${segment(endpointId, "endpointId")}/deliveries/replay`,
      { method: "POST", body: input, ...requestFields(options) },
    );
  }

  /** Sends a signed synthetic `webhook.test` event to verify an endpoint. */
  sendTestEvent(
    emitterId: string,
    endpointId: string,
    options: RequestOptions = {},
  ): Promise<KilaResponse<{ delivery: WebhookDelivery; job: Job }>> {
    return this.http.json<{ delivery: WebhookDelivery; job: Job }>(
      `/v1/emitters/${segment(emitterId, "emitterId")}/webhooks/${segment(endpointId, "endpointId")}/test`,
      { method: "POST", ...requestFields(options) },
    );
  }

  getDelivery(
    emitterId: string,
    deliveryId: string,
    options: RequestOptions = {},
  ): Promise<KilaResponse<{ delivery: WebhookDelivery; job: Job | null }>> {
    return this.http.json<{ delivery: WebhookDelivery; job: Job | null }>(
      `/v1/emitters/${segment(emitterId, "emitterId")}/webhook-deliveries/${segment(deliveryId, "deliveryId")}`,
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

function queryString(
  values: Record<string, string | number | undefined>,
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined) params.set(key, String(value));
  }
  const serialized = params.toString();
  return serialized ? `?${serialized}` : "";
}
