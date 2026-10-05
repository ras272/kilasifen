/** Values accepted by the JSON transport. */
export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type DecimalValue = number | string;
export type NumericCode = number | string;
export type IsoDate = string;
export type IsoDateTime = string;

export interface ApiSuccess<T> {
  data: T;
  correlation_id: string;
}

export interface ApiErrorPayload {
  code: string;
  message: string;
  category: string;
  correlation_id: string;
  details?: Record<string, unknown> | null;
}

/**
 * One entry of `details.errors` in a `422 request.validation_failed` error.
 * The submitted value is never echoed back.
 */
export interface ValidationErrorItem {
  loc: Array<string | number>;
  message: string;
  type: string;
  /**
   * Stable code of the fiscal rule the payload breaks, such as
   * `documents.cliente.tipo_contribuyente_required`. Absent for plain
   * contract errors (a missing field, a pattern).
   */
  code?: string;
}

/** `details` of a `422 request.validation_failed` error. */
export interface ValidationErrorDetails {
  errors: ValidationErrorItem[];
}

export interface ApiErrorEnvelope {
  error: ApiErrorPayload;
}

export interface KilaResponse<T> {
  data: T;
  correlationId: string;
  status: number;
}

export interface RequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
  headers?: Record<string, string>;
}

/** The five deterministic SIFEN outcomes of the API test runtime. */
export type SandboxOutcome =
  | "approved"
  | "approved_with_observation"
  | "rejected"
  | "transport_timeout"
  | "accepted_but_response_lost";

export interface CreateOptions extends RequestOptions {
  /**
   * Stable identifier for one fiscal intent. Reusing it returns the original
   * document instead of emitting another one. It travels as the body field
   * `idempotency_key`, the one the API reads; the `Idempotency-Key` header is
   * sent too but the API ignores it today.
   */
  idempotencyKey?: string;
  /**
   * Deterministic SIFEN result for automated tests. The API answers
   * `422 sandbox.test_runtime_required` outside a deployment with
   * `KILA_SIFEN_ENVIRONMENT=test`.
   */
  sandboxOutcome?: SandboxOutcome;
}

export interface PublicProcurement {
  modalidad: NumericCode;
  entidad: NumericCode;
  anio: NumericCode;
  secuencia: NumericCode;
  fecha_codigo: IsoDate;
}

export interface EconomicActivity {
  codigo: string;
  descripcion: string;
}

export interface GenerationResponsible {
  /** iTipIDRespDE: 1-4, or 9 together with `descripcion_tipo_documento`. */
  tipo_documento: 1 | 2 | 3 | 4 | 9;
  /** Real document type (9-41 characters); only with `tipo_documento` 9. */
  descripcion_tipo_documento?: string;
  numero_documento: string;
  nombre: string;
  /** dCarRespDE: 4-100 characters. */
  cargo: string;
}

/**
 * Optional echo of the emitter identity. `ruc`, `dv` and `razon_social` must
 * match the registered emitter (422 otherwise); gEmis comes from the emitter
 * fiscal profile.
 */
export interface EmitterData {
  ruc?: string;
  dv?: string;
  razon_social?: string;
  /** @deprecated Ignored: set it in the emitter fiscal profile. */
  direccion?: string;
  /** @deprecated Ignored: set it in the emitter fiscal profile. */
  numero?: NumericCode;
  /** @deprecated Ignored: set it in the emitter fiscal profile. */
  complemento_1?: string;
  /** @deprecated Ignored: set it in the emitter fiscal profile. */
  complemento_2?: string;
  /** @deprecated Ignored: set it in the emitter fiscal profile. */
  departamento?: NumericCode;
  /** @deprecated Ignored: set it in the emitter fiscal profile. */
  descripcion_departamento?: string;
  /** @deprecated Ignored: set it in the emitter fiscal profile. */
  distrito?: NumericCode;
  /** @deprecated Ignored: set it in the emitter fiscal profile. */
  descripcion_distrito?: string;
  /** @deprecated Ignored: set it in the emitter fiscal profile. */
  ciudad?: NumericCode;
  /** @deprecated Ignored: set it in the emitter fiscal profile. */
  descripcion_ciudad?: string;
  /** @deprecated Ignored: set it in the emitter fiscal profile. */
  telefono?: string;
  /** @deprecated Ignored: set it in the emitter fiscal profile. */
  email?: string;
  /** @deprecated Ignored: set it in the emitter fiscal profile. */
  actividad_economica?: EconomicActivity;
  responsable_generacion?: GenerationResponsible;
}

export interface Customer {
  naturaleza?: number;
  /** iTiOpe: a non-taxpayer only allows 2 (B2C) or 4 (B2F). */
  tipo_operacion?: number;
  /** iTiContRec: mandatory with `ruc`; there is no default. */
  tipo_contribuyente?: number;
  /** dRucRec, optionally as `RUC-DV`; the DV is mandatory and checked. */
  ruc?: string;
  dv?: string;
  /** iTipIDRec: 1-6 or 9; 5 (innominado) only in B2C invoices. */
  tipo_documento_identidad?: number;
  /** Real document type (9-41 characters) when `tipo_documento_identidad` is 9. */
  descripcion_tipo_documento?: string;
  numero_documento_identidad?: string;
  razon_social?: string;
  nombre?: string;
  direccion?: string;
  numero_casa?: NumericCode;
  /** cPaisRec: other than PRY only for B2F. */
  pais_codigo?: string;
  /** Taken from the official country catalog; must match when sent. */
  pais_descripcion?: string;
  departamento?: NumericCode;
  descripcion_departamento?: string;
  distrito?: NumericCode;
  descripcion_distrito?: string;
  ciudad?: NumericCode;
  descripcion_ciudad?: string;
  telefono?: string;
  celular?: string;
  email?: string;
  codigo_cliente?: string;
  compras_publicas?: PublicProcurement;
}

export interface CardPayment {
  marca: NumericCode;
  razon_social_procesadora?: string;
  ruc_procesadora?: string;
  dv_procesadora?: string;
  forma_procesamiento: NumericCode;
  codigo_autorizacion?: NumericCode;
  nombre_titular?: string;
  ultimos_4?: NumericCode;
}

export interface Payment {
  tipo: NumericCode;
  monto: DecimalValue;
  /** cMoneTiPag, an ISO 4217 code; omitted, the currency of the operation. */
  moneda?: string;
  /** @deprecated Ignored: dDMoneTiPag is the official name of `moneda` (1555). */
  moneda_descripcion?: string;
  /**
   * dTiCamTiPag (up to 4 decimals): mandatory when `moneda` is not PYG (1556)
   * and refused when it is PYG (1557). Omitted for a payment in the currency
   * of the operation, the operation `tipo_cambio` is used.
   */
  tipo_cambio?: DecimalValue;
  numero_cheque?: NumericCode;
  banco?: string;
  tarjeta?: CardPayment;
}

export interface Installment {
  monto: DecimalValue;
  fecha_vencimiento?: IsoDate;
  /** cMoneCuo, an ISO 4217 code; omitted, the currency of the operation. */
  moneda?: string;
}

export interface CreditCondition {
  tipo: NumericCode;
  descripcion?: string;
  plazo_descripcion?: string;
  /**
   * dMonEnt. Requires `formas_pago` in the operation condition with the
   * payments of that initial delivery, which must add up to it (1551).
   */
  monto_entrega_inicial?: DecimalValue;
  cuotas?: Installment[];
}

export interface OperationCondition {
  tipo?: NumericCode;
  /**
   * gPaConEIni. Contado: they add up to dTotGralOpe (0.50 tolerance); without
   * them one cash payment of the total is written. Credito: only with
   * `monto_entrega_inicial`, adding up to it (1551/1552).
   */
  formas_pago?: Payment[];
  credito?: CreditCondition;
}

export type TaxAffectation = 1 | 2 | 3 | 4 | "gravado" | "exonerado" | "exento" | "gravado_parcial";

export interface DocumentItem {
  codigo_interno?: string;
  descripcion: string;
  unidad_medida?: NumericCode;
  descripcion_unidad?: string;
  cantidad: DecimalValue;
  precio_unitario: DecimalValue;
  descuento_particular?: DecimalValue;
  /**
   * dDescGloItem. Derived as `porcentaje_descuento_global * precio_unitario /
   * 100` (NT 01); if sent it must match that within 0.8 (1862).
   */
  descuento_global?: DecimalValue;
  anticipo_particular?: DecimalValue;
  anticipo_global?: DecimalValue;
  cdc_anticipo?: string;
  afectacion?: TaxAffectation;
  /**
   * dPropIVA: mandatory and strictly between 0 and 100 with `gravado_parcial`
   * (1906); if sent, 100 with `gravado` (1904) and 0 with `exento` or
   * `exonerado` (1905).
   */
  proporcion_gravada?: DecimalValue;
  tasa?: 0 | 5 | 10;
  tipo_cambio_item?: DecimalValue;
}

export interface AssociatedDocument {
  tipo?: 1 | 2 | 3 | "electronico" | "impreso" | "constancia_electronica";
  cdc?: string;
  timbrado?: NumericCode;
  establecimiento?: NumericCode;
  punto?: NumericCode;
  numero?: NumericCode;
  fecha_emision?: IsoDate;
  tipo_documento_impreso?: number;
  tipo_constancia?: number;
  numero_constancia?: string;
  numero_control?: string;
}

export interface BaseFiscalDocument {
  establecimiento?: NumericCode;
  punto?: NumericCode;
  numero?: NumericCode;
  fecha?: IsoDateTime;
  fecha_emision?: IsoDateTime;
  /** cMoneOpe: an ISO 4217 code of the XSD (default PYG). */
  moneda?: string;
  /** dTiCam: up to 4 decimals. */
  tipo_cambio?: DecimalValue;
  condicion_tipo_cambio?: number;
  /**
   * dPorcDescTotal: global discount percentage (default 0), applied to every
   * item as dDescGloItem (NT 01, 1860/1862).
   */
  porcentaje_descuento_global?: DecimalValue;
  /**
   * dRedon. `ninguno` (default) writes 0; `multiplo_50` rounds dTotOpe down
   * to a multiple of 50 Gs, only in PYG. Foreign currencies are never rounded.
   */
  redondeo?: "ninguno" | "multiplo_50";
  tipo_transaccion?: NumericCode;
  /** iTImp. 2 (ISC) is refused: the typed contracts cannot express it. */
  tipo_impuesto?: NumericCode;
  /** Optional; must match the emitter fiscal profile (iTipCont). */
  tipo_contribuyente?: number;
  /**
   * dCodSeg. Omit it and the platform draws a random one; if sent it must be
   * random, from 1 to 999999999 and different from the document number.
   */
  codigo_seguridad?: NumericCode;
  emisor?: EmitterData;
  cliente: Customer;
  condicion_operacion?: OperationCondition;
  /** Alias accepted by the API for condicion_operacion. */
  condicion?: OperationCondition;
  items: DocumentItem[];
  documento_asociado?: AssociatedDocument | AssociatedDocument[];
  metadata?: Record<string, JsonValue>;
}

export interface Factura extends BaseFiscalDocument {
  tipo_documento?: 1;
  indicador_presencia?: NumericCode;
  factura?: Record<string, JsonValue>;
}

/**
 * iMotEmi (MT v150 E401): 1 `devolucion_y_ajuste`, 2 `devolucion`,
 * 3 `descuento`, 4 `bonificacion`, 5 `credito_incobrable`,
 * 6 `recupero_costo`, 7 `recupero_gasto` or 8 `ajuste_precio`. Always send
 * the real motive: when omitted, the platform currently informs 1.
 */
export type IssueMotive =
  | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8
  | "devolucion_y_ajuste"
  | "devolucion"
  | "descuento"
  | "bonificacion"
  | "credito_incobrable"
  | "recupero_costo"
  | "recupero_gasto"
  | "ajuste_precio";

export interface NotaCredito extends BaseFiscalDocument {
  tipo_documento?: 5;
  motivo_emision?: IssueMotive;
  documento_asociado: AssociatedDocument;
  nota_credito?: Record<string, JsonValue>;
}

export interface NotaDebito extends BaseFiscalDocument {
  tipo_documento?: 6;
  motivo_emision?: IssueMotive;
  documento_asociado: AssociatedDocument;
  nota_debito?: Record<string, JsonValue>;
}

export interface FacturaCreateInput {
  external_id?: string;
  factura: Factura;
}

export interface NotaCreditoCreateInput {
  external_id?: string;
  nota_credito: NotaCredito;
}

export interface NotaDebitoCreateInput {
  external_id?: string;
  nota_debito: NotaDebito;
}

export interface Document {
  id: string;
  emitter_id: string;
  external_id: string | null;
  idempotency_key: string | null;
  document_type: string;
  payload_snapshot: Record<string, unknown> | null;
  generated_xml: string | null;
  signed_xml: string | null;
  sifen_request_xml: string | null;
  sifen_response_raw: string | null;
  last_query_request_xml: string | null;
  last_query_response_raw: string | null;
  last_query_at: IsoDateTime | null;
  cdc: string | null;
  internal_status: string;
  sifen_status: string | null;
  sifen_result_code: string | null;
  sifen_result_message: string | null;
  establishment: string | null;
  point: string | null;
  document_number: number | null;
  /** Fiscal warnings found at creation, such as an extemporaneous emission date. */
  fiscal_warnings: string[];
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface Job {
  id: string;
  emitter_id: string | null;
  related_entity_type: string | null;
  related_entity_id: string | null;
  job_type: string;
  status: string;
  attempts: number;
  error_snapshot: Record<string, unknown> | null;
  scheduled_at: IsoDateTime | null;
  started_at: IsoDateTime | null;
  finished_at: IsoDateTime | null;
  worker_correlation_id: string | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface DocumentWithJob {
  document: Document;
  job: Job | null;
}

export interface CreatedDocument {
  document: Document;
  job: Job;
}

/** found (0422), not_found_or_not_approved (0420) or error (any other code). */
export type DocumentQueryStatus =
  | "found"
  | "not_found_or_not_approved"
  | "error";

/** One event SIFEN registered on the CDC (xContEv). */
export interface RegisteredEvent {
  kind: string;
  cdc: string | null;
  protocol: string | null;
}

export interface DocumentQuery {
  document_id: string;
  cdc: string;
  status: DocumentQueryStatus | string;
  result_code: string | null;
  result_message: string | null;
  content_xml: string | null;
  processed_at: IsoDateTime | null;
  sifen_protocol: string | null;
  cancelled: boolean;
  events: RegisteredEvent[];
}

export interface ReconciledDocument {
  document_query: DocumentQuery;
}

export interface Pagination {
  limit: number;
  offset: number;
  count: number;
}

export interface DocumentListItem extends DocumentWithJob {}

export interface DocumentList {
  documents: DocumentListItem[];
  pagination: Pagination;
}

export interface DocumentListOptions extends RequestOptions {
  limit?: number;
  offset?: number;
  internalStatus?: string;
  documentType?: string;
  externalId?: string;
  cdc?: string;
}

export interface Taxpayer {
  ruc: string;
  legal_name: string;
  state_code: string | null;
  state: string | null;
  electronic_taxpayer: boolean | null;
}

export interface RucQuery {
  queried_ruc: string;
  status: string;
  result_code: string | null;
  result_message: string | null;
  taxpayer: Taxpayer | null;
}

export interface FiscalEvent {
  id: string;
  emitter_id: string;
  document_id: string | null;
  event_type: string;
  input_payload: Record<string, unknown> | null;
  generated_xml: string | null;
  signed_xml: string | null;
  sifen_request_xml: string | null;
  sifen_response_raw: string | null;
  status: string;
  sifen_result_code: string | null;
  sifen_result_message: string | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface EventWithJob {
  event: FiscalEvent;
  job: Job | null;
}

export interface CreatedEvent {
  event: FiscalEvent;
  job: Job;
}

export interface CancelDocumentInput {
  motivo: string;
}

/**
 * `fe_exportacion`, `fe_importacion` and `comprobante_retencion` (iTiDE 2, 3
 * and 8) are not DE types in v150 (DE_Types_v150.xsd): there are no such
 * numbers to inutilize and SIFEN may answer 4060.
 */
export type InutilizationDocumentType =
  | "factura"
  | "fe_exportacion"
  | "fe_importacion"
  | "autofactura"
  | "nota_credito"
  | "nota_debito"
  | "nota_remision"
  | "comprobante_retencion";

export interface InutilizeNumbersInput {
  timbrado: string;
  document_type: InutilizationDocumentType;
  establishment: string;
  point: string;
  numero_desde: number;
  numero_hasta: number;
  motivo: string;
  /** Optional dSerieNum (NT 10 §1.7): two capital letters. */
  serie?: string | null;
}

export interface InutilizedRange {
  id: string;
  emitter_id: string;
  document_type: string;
  establishment: string;
  point: string;
  numero_desde: number;
  numero_hasta: number;
  timbrado: string;
  event_id: string;
  sifen_protocol: string | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface CreatedInutilization extends CreatedEvent {
  inutilization: InutilizedRange;
  /** "inutilization.extemporaneous" when past day 15 of the next month. */
  warnings: string[];
}

export interface WebhookRetryPolicy {
  max_attempts?: number;
}

export interface WebhookEndpointCreateInput {
  url: string;
  secret: string;
  /**
   * Event types to receive; omitted, all of them. Matched exactly or by a
   * `.*` prefix: `*`, `document.*`, `document.<status>`, `document.updated`
   * and `webhook.test`. A misspelled type is accepted and never matches.
   */
  event_subscriptions?: string[] | null;
  retry_policy?: WebhookRetryPolicy | null;
}

export interface WebhookEndpointUpdateInput {
  url?: string;
  secret?: string;
  event_subscriptions?: string[] | null;
  retry_policy?: WebhookRetryPolicy;
  is_active?: boolean;
}

export interface WebhookEndpoint {
  id: string;
  emitter_id: string | null;
  url: string;
  event_subscriptions: string[] | null;
  is_active: boolean;
  retry_policy: Record<string, unknown> | null;
  secret_configured: boolean;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface WebhookDelivery {
  id: string;
  webhook_endpoint_id: string;
  event_type: string;
  payload_snapshot: Record<string, unknown> | null;
  request_body: string | null;
  attempt_number: number;
  request_at: IsoDateTime | null;
  response_code: number | null;
  response_body_snapshot: string | null;
  final_status: string;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

/**
 * Re-delivers an event KilaSifen already generated for this emitter. The new
 * delivery copies its type, data and occurred_at and gets a new delivery ID.
 */
export interface WebhookReplayInput {
  delivery_id: string;
}
