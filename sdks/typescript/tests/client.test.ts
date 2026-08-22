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
    expect(JSON.parse(String(init?.body))).toMatchObject({
      external_id: "sale-123",
      idempotency_key: "sale-123",
    });
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
