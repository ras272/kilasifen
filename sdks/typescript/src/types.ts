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

export type SandboxOutcome =
  | "approved"
  | "approved_with_observation"
  | "rejected";

export interface CreateOptions extends RequestOptions {
  /**
   * Stable identifier for one fiscal intent. Reusing it returns the original
   * document instead of emitting another one.
   */
  idempotencyKey?: string;
  /**
   * Deterministic SIFEN result for automated tests. The API rejects this
   * header outside its test runtime.
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
  tipo_documento?: number;
  numero_documento: string;
  nombre: string;
  cargo: string;
}

export interface EmitterData {
  ruc?: string;
  dv?: string;
  razon_social?: string;
  direccion?: string;
  numero?: NumericCode;
  complemento_1?: string;
  complemento_2?: string;
  departamento?: NumericCode;
  descripcion_departamento?: string;
  distrito?: NumericCode;
  descripcion_distrito?: string;
  ciudad?: NumericCode;
  descripcion_ciudad?: string;
  telefono?: string;
  email?: string;
  actividad_economica?: EconomicActivity;
  responsable_generacion?: GenerationResponsible;
}

export interface Customer {
  naturaleza?: number;
  tipo_operacion?: number;
  tipo_contribuyente?: number;
  ruc?: string;
  dv?: string;
  tipo_documento_identidad?: number;
  numero_documento_identidad?: string;
  razon_social?: string;
  nombre?: string;
  direccion?: string;
  numero_casa?: NumericCode;
  pais_codigo?: string;
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
  moneda?: string;
  moneda_descripcion?: string;
  tipo_cambio?: DecimalValue;
  numero_cheque?: NumericCode;
  banco?: string;
  tarjeta?: CardPayment;
}

export interface Installment {
  monto: DecimalValue;
  fecha_vencimiento?: IsoDate;
  moneda?: string;
}

export interface CreditCondition {
  tipo: NumericCode;
  descripcion?: string;
  plazo_descripcion?: string;
  monto_entrega_inicial?: DecimalValue;
  cuotas?: Installment[];
}

export interface OperationCondition {
  tipo?: NumericCode;
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
  descuento_global?: DecimalValue;
  anticipo_particular?: DecimalValue;
  anticipo_global?: DecimalValue;
  cdc_anticipo?: string;
  afectacion?: TaxAffectation;
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
  moneda?: string;
  tipo_cambio?: DecimalValue;
  condicion_tipo_cambio?: number;
  tipo_transaccion?: NumericCode;
  tipo_impuesto?: NumericCode;
  tipo_contribuyente?: number;
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

export interface NotaCredito extends BaseFiscalDocument {
  tipo_documento?: 5;
  motivo_emision?: NumericCode;
  documento_asociado: AssociatedDocument;
  nota_credito?: Record<string, JsonValue>;
}

export interface NotaDebito extends BaseFiscalDocument {
  tipo_documento?: 6;
  motivo_emision?: NumericCode;
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
