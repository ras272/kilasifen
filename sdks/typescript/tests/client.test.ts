import { describe, expect, it, vi } from "vitest";

import {
  KilaSifen,
  KilaSifenConnectionError,
  KilaSifenError,
  isKilaSifenError,
} from "../src";

const DOCUMENT = {
  id: "doc_123",
  emitter_id: "emitter/123",
  external_id: "sale-123",
  idempotency_key: "sale-123",
  document_type: "factura",
  payload_snapshot: null,
  generated_xml: null,
  signed_xml: null,
  sifen_request_xml: null,
  sifen_response_raw: null,
  last_query_request_xml: null,
  last_query_response_raw: null,
  last_query_at: null,
  cdc: null,
  internal_status: "queued",
  sifen_status: null,
  sifen_result_code: null,
  sifen_result_message: null,
  establishment: null,
  point: null,
  document_number: null,
  created_at: "2026-08-22T12:00:00Z",
  updated_at: "2026-08-22T12:00:00Z",
};

const JOB = {
  id: "job_123",
  emitter_id: "emitter/123",
  related_entity_type: "document",
  related_entity_id: "doc_123",
  job_type: "document.emit",
  status: "queued",
  attempts: 0,
  error_snapshot: null,
  scheduled_at: null,
  started_at: null,
  finished_at: null,
  worker_correlation_id: null,
  created_at: "2026-08-22T12:00:00Z",
  updated_at: "2026-08-22T12:00:00Z",
};

function success(data: unknown, status = 200): Response {
  return Response.json({ data, correlation_id: "corr_123" }, { status });
}

describe("KilaSifen client", () => {
  it("emits a factura with authentication and idempotency in header and body", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      success({ document: DOCUMENT, job: JOB }, 201),
    );
    const client = new KilaSifen({
      apiKey: "sk_test_123",
      baseUrl: "https://api.example.test/",
      fetch: fetchMock,
    });

    const response = await client.facturas.create(
      "emitter/123",
      {
        external_id: "sale-123",
        factura: {
          cliente: { ruc: "80069563-1", razon_social: "TIPS S.A." },
          items: [{ descripcion: "Producto", cantidad: 1, precio_unitario: 1000 }],
        },
      },
      { idempotencyKey: "sale-123" },
    );

    expect(response).toEqual({
      data: { document: DOCUMENT, job: JOB },
      correlationId: "corr_123",
      status: 201,
    });
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe(
      "https://api.example.test/v1/emitters/emitter%2F123/documents/facturas",
    );
    const headers = new Headers(init?.headers);
    expect(headers.get("X-API-Key")).toBe("sk_test_123");
    expect(headers.get("Idempotency-Key")).toBe("sale-123");
    expect(headers.has("X-Kila-Test-Outcome")).toBe(false);
    expect(JSON.parse(String(init?.body))).toMatchObject({
      external_id: "sale-123",
      idempotency_key: "sale-123",
    });
  });

  it("sends a closed sandbox outcome only when explicitly requested", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      success({ document: DOCUMENT, job: JOB }, 201),
    );
    const client = new KilaSifen({
      apiKey: "sk_test_123",
      baseUrl: "https://api.example.test",
      fetch: fetchMock,
    });

    await client.facturas.create(
      "emitter_1",
      {
        factura: {
          cliente: { ruc: "80069563-1", razon_social: "TIPS S.A." },
          items: [{ descripcion: "Sandbox", cantidad: 1, precio_unitario: 1000 }],
        },
      },
      { sandboxOutcome: "approved_with_observation" },
    );

    const [, init] = fetchMock.mock.calls[0] ?? [];
    expect(new Headers(init?.headers).get("X-Kila-Test-Outcome")).toBe(
      "approved_with_observation",
    );
  });

  it("prevents bypassing the typed sandbox option through custom headers", () => {
    const client = new KilaSifen({
      apiKey: "sk_test_123",
      baseUrl: "https://api.example.test",
      fetch: vi.fn<typeof fetch>(),
    });

    expect(() => client.facturas.create(
      "emitter_1",
      {
        factura: {
          cliente: { ruc: "80069563-1", razon_social: "TIPS S.A." },
          items: [{ descripcion: "Sandbox", cantidad: 1, precio_unitario: 1000 }],
        },
      },
      { headers: { "x-kila-test-outcome": "anything" } },
    )).toThrow("Use sandboxOutcome");
  });

  it("rejects invalid sandbox outcomes at runtime for JavaScript consumers", () => {
    const client = new KilaSifen({
      apiKey: "sk_test_123",
      baseUrl: "https://api.example.test",
      fetch: vi.fn<typeof fetch>(),
    });

    expect(() => client.facturas.create(
      "emitter_1",
      {
        factura: {
          cliente: { ruc: "80069563-1", razon_social: "TIPS S.A." },
          items: [{ descripcion: "Sandbox", cantidad: 1, precio_unitario: 1000 }],
        },
      },
      { sandboxOutcome: "unknown" as never },
    )).toThrow("sandboxOutcome must be");
  });

  it("uses the typed nota de credito endpoint", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      success({ document: { ...DOCUMENT, document_type: "nota_credito" }, job: JOB }, 201),
    );
    const client = new KilaSifen({
      apiKey: "sk_test_123",
      baseUrl: "https://api.example.test",
      fetch: fetchMock,
    });

    await client.notasCredito.create("emitter_1", {
      nota_credito: {
        cliente: { ruc: "80069563-1", razon_social: "TIPS S.A." },
        documento_asociado: { cdc: "01800123450001001000000012026010112345678901" },
        items: [{ descripcion: "Descuento", cantidad: 1, precio_unitario: 500 }],
      },
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "https://api.example.test/v1/emitters/emitter_1/documents/notas-credito",
    );
  });

  it("emits a nota de debito with its typed contract and idempotency", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      success({ document: { ...DOCUMENT, document_type: "nota_debito" }, job: JOB }, 201),
    );
    const client = new KilaSifen({
      apiKey: "sk_test_123",
      baseUrl: "https://api.example.test",
      fetch: fetchMock,
    });

    const response = await client.notasDebito.create(
      "emitter_1",
      {
        external_id: "recupero-77",
        nota_debito: {
          motivo_emision: "recupero_costo",
          cliente: { ruc: "80069563-1", razon_social: "TIPS S.A." },
          documento_asociado: {
            cdc: "01800123450001001000000012026010112345678901",
          },
          items: [
            {
              descripcion: "Recupero de costo",
              cantidad: 1,
              precio_unitario: 500,
            },
          ],
        },
      },
      { idempotencyKey: "recupero-77-v1" },
    );

    expect(response.data.document.document_type).toBe("nota_debito");
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "https://api.example.test/v1/emitters/emitter_1/documents/notas-debito",
    );
    const [, init] = fetchMock.mock.calls[0] ?? [];
    expect(new Headers(init?.headers).get("Idempotency-Key")).toBe("recupero-77-v1");
    expect(JSON.parse(String(init?.body))).toMatchObject({
      external_id: "recupero-77",
      idempotency_key: "recupero-77-v1",
      nota_debito: {
        motivo_emision: "recupero_costo",
      },
    });
  });

  it("retrieves documents and jobs with escaped path identifiers", async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(success({ document: DOCUMENT, job: JOB }))
      .mockResolvedValueOnce(success({ job: JOB }));
    const client = new KilaSifen({
      apiKey: "sk_test_123",
      baseUrl: "https://api.example.test",
      fetch: fetchMock,
    });

    await client.documents.get("emitter one", "doc/123");
    await client.jobs.get("emitter one", "job/123");

    expect(fetchMock.mock.calls[0]?.[0]).toContain("emitter%20one/documents/doc%2F123");
    expect(fetchMock.mock.calls[1]?.[0]).toContain("emitter%20one/jobs/job%2F123");
  });

  it("reconciles an uncertain document without a request body", async () => {
    const documentQuery = {
      document_id: "doc/123",
      cdc: "01800123450001001000000012026010112345678901",
      status: "found",
      result_code: "0300",
      result_message: "Aprobado",
      content_xml: "<rDE version='150'/>",
      processed_at: "2026-08-22T12:00:00Z",
    };
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      success({ document_query: documentQuery }),
    );
    const client = new KilaSifen({
      apiKey: "sk_test_123",
      baseUrl: "https://api.example.test",
      fetch: fetchMock,
    });

    const response = await client.documents.reconcile("emitter one", "doc/123");

    expect(response.data.document_query).toEqual(documentQuery);
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe(
      "https://api.example.test/v1/emitters/emitter%20one/queries/documents/doc%2F123/reconcile",
    );
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeUndefined();
  });

  it("lists and queries documents with encoded filters", async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(success({ documents: [], pagination: { limit: 25, offset: 0, count: 0 } }))
      .mockResolvedValueOnce(success({ document_query: { document_id: "doc_1", cdc: "1", status: "found" } }))
      .mockResolvedValueOnce(success({ ruc_query: { queried_ruc: "80069563", status: "found", taxpayer: null } }));
    const client = new KilaSifen({
      apiKey: "sk_test_123",
      baseUrl: "https://api.example.test",
      fetch: fetchMock,
    });

    await client.documents.list("emitter_1", { limit: 25, externalId: "sale/1" });
    await client.documents.query("emitter_1", "doc_1");
    await client.queries.ruc("emitter_1", "80069563-1");

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "https://api.example.test/v1/emitters/emitter_1/documents?limit=25&external_id=sale%2F1",
    );
    expect(fetchMock.mock.calls[1]?.[0]).toContain("/queries/documents/doc_1");
    expect(fetchMock.mock.calls[2]?.[0]).toContain("/queries/ruc/80069563-1");
  });

  it("creates typed cancellation and inutilization events", async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(success({ event: { id: "event_1" }, job: JOB }, 201))
      .mockResolvedValueOnce(success({ event: { id: "event_2" }, job: JOB, inutilization: { id: "range_1" } }, 201));
    const client = new KilaSifen({
      apiKey: "sk_test_123",
      baseUrl: "https://api.example.test",
      fetch: fetchMock,
    });

    await client.events.cancel("emitter_1", "doc/1", { motivo: "Error de datos" });
    await client.events.inutilize("emitter_1", {
      timbrado: "12345678",
      document_type: "factura",
      establishment: "001",
      point: "001",
      numero_desde: 10,
      numero_hasta: 12,
      motivo: "Rango no utilizado",
    });

    expect(fetchMock.mock.calls[0]?.[0]).toContain("/documents/doc%2F1/cancel");
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toMatchObject({
      numero_desde: 10,
      numero_hasta: 12,
    });
  });

  it("manages webhook endpoints and explicit replay", async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(success({ webhook_endpoint: { id: "wh_1" } }, 201))
      .mockResolvedValueOnce(success({ webhook_endpoints: [] }))
      .mockResolvedValueOnce(success({ webhook_endpoint: { id: "wh_1", is_active: false } }))
      .mockResolvedValueOnce(success({ delivery: { id: "delivery_1" }, job: JOB }, 201));
    const client = new KilaSifen({
      apiKey: "sk_test_123",
      baseUrl: "https://api.example.test",
      fetch: fetchMock,
    });

    await client.webhooks.create("emitter_1", {
      url: "https://erp.example.com/kila",
      secret: "12345678901234567890123456789012",
      event_subscriptions: ["document.approved"],
    });
    await client.webhooks.list("emitter_1");
    await client.webhooks.update("emitter_1", "wh_1", {
      secret: "new-secret-123456789012345678901234",
      is_active: false,
    });
    await client.webhooks.replay("emitter_1", "wh_1", {
      event_type: "document.approved",
      payload: { document_id: "doc_1" },
    });

    expect(fetchMock.mock.calls[0]?.[0]).toContain("/webhooks");
    expect(fetchMock.mock.calls[2]?.[1]?.method).toBe("PATCH");
    expect(fetchMock.mock.calls[3]?.[0]).toContain("/webhooks/wh_1/deliveries/replay");
    expect(() => client.webhooks.update("emitter_1", "wh_1", {})).toThrow(
      "at least one field",
    );
  });

  it("throws a typed KilaSifen error from an API error envelope", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      Response.json(
        {
          error: {
            code: "documents.not_found",
            message: "Resource was not found.",
            category: "not_found",
            correlation_id: "corr_error",
            details: { document_id: "missing" },
          },
        },
        { status: 404 },
      ),
    );
    const client = new KilaSifen({
      apiKey: "sk_test_123",
      baseUrl: "https://api.example.test",
      fetch: fetchMock,
    });

    const error = await client.documents.get("emitter_1", "missing").catch((caught: unknown) => caught);

    expect(isKilaSifenError(error)).toBe(true);
    expect(error).toBeInstanceOf(KilaSifenError);
    expect(error).toMatchObject({
      status: 404,
      code: "documents.not_found",
      category: "not_found",
      correlationId: "corr_error",
      retryable: false,
    });
  });

  it("keeps field details from a 422 validation envelope", async () => {
    const client = new KilaSifen({
      apiKey: "sk_test_123",
      baseUrl: "https://api.example.test",
      fetch: vi.fn<typeof fetch>().mockResolvedValue(
        Response.json(
          {
            error: {
              code: "request.validation_failed",
              message: "Request validation failed.",
              category: "validation",
              correlation_id: "corr_422",
              details: {
                errors: [
                  { loc: ["body", "factura", "items"], message: "Field required", type: "missing" },
                ],
              },
            },
          },
          { status: 422 },
        ),
      ),
    });

    const error = await client.facturas
      .create("emitter_1", { factura: {} as never })
      .catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(KilaSifenError);
    expect(error).toMatchObject({
      status: 422,
      code: "request.validation_failed",
      category: "validation",
      correlationId: "corr_422",
      retryable: false,
      details: {
        errors: [{ loc: ["body", "factura", "items"], message: "Field required", type: "missing" }],
      },
    });
  });

  it("treats a non-JSON 5xx from a proxy as a retryable HTTP error", async () => {
    const client = new KilaSifen({
      apiKey: "sk_test_123",
      baseUrl: "https://api.example.test",
      fetch: vi.fn<typeof fetch>().mockResolvedValue(
        new Response("<html>Bad Gateway</html>", {
          status: 502,
          headers: { "Content-Type": "text/html", "X-Correlation-ID": "corr_502" },
        }),
      ),
    });

    const error = await client.documents.get("emitter_1", "doc_1").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(KilaSifenConnectionError);
    expect(error).toMatchObject({
      code: "sdk.http_error",
      status: 502,
      correlationId: "corr_502",
      retryable: true,
    } satisfies Partial<KilaSifenConnectionError>);
  });

  it("does not retry a 4xx that lacks the error envelope", async () => {
    const client = new KilaSifen({
      apiKey: "sk_test_123",
      baseUrl: "https://api.example.test",
      fetch: vi.fn<typeof fetch>().mockResolvedValue(
        Response.json({ detail: "Not Found" }, { status: 404 }),
      ),
    });

    await expect(client.documents.get("emitter_1", "doc_1")).rejects.toMatchObject({
      code: "sdk.http_error",
      status: 404,
      correlationId: null,
      retryable: false,
    } satisfies Partial<KilaSifenConnectionError>);
  });

  it("rejects a non-JSON 2xx body as an invalid response", async () => {
    const client = new KilaSifen({
      apiKey: "sk_test_123",
      baseUrl: "https://api.example.test",
      fetch: vi.fn<typeof fetch>().mockResolvedValue(new Response("ok", { status: 200 })),
    });

    await expect(client.documents.get("emitter_1", "doc_1")).rejects.toMatchObject({
      code: "sdk.invalid_response",
      retryable: false,
    } satisfies Partial<KilaSifenConnectionError>);
  });

  it("rejects malformed success envelopes", async () => {
    const client = new KilaSifen({
      apiKey: "sk_test_123",
      baseUrl: "https://api.example.test",
      fetch: vi.fn<typeof fetch>().mockResolvedValue(Response.json({ data: {} })),
    });

    await expect(client.documents.get("emitter_1", "doc_1")).rejects.toMatchObject({
      code: "sdk.invalid_response",
      retryable: false,
    } satisfies Partial<KilaSifenConnectionError>);
  });

  it("validates client and identifier inputs before transport", () => {
    expect(() => new KilaSifen({ apiKey: "", baseUrl: "https://api.example.test" })).toThrow(TypeError);
    const client = new KilaSifen({ apiKey: "key", baseUrl: "https://api.example.test" });
    expect(() => client.documents.get("", "doc_1")).toThrow(TypeError);
  });
});
