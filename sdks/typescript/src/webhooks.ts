const SIGNATURE_VERSION = "v1";
const DEFAULT_TOLERANCE_SECONDS = 300;

export type WebhookVerificationReason =
  | "verified"
  | "missing_header"
  | "invalid_timestamp"
  | "stale_timestamp"
  | "unsupported_version"
  | "invalid_signature"
  | "duplicate_delivery";

export interface WebhookVerification {
  valid: boolean;
  reason: WebhookVerificationReason;
  deliveryId: string | null;
  eventType: string | null;
}

export interface VerifyWebhookOptions {
  /** Exact request bytes, before JSON parsing. */
  rawBody: string | Uint8Array;
  secret: string;
  headers: Headers | Record<string, string | undefined>;
  toleranceSeconds?: number;
  now?: Date;
  /** Persistent replay lookup supplied by the integrator. */
  isDeliveryProcessed?: (deliveryId: string) => boolean | Promise<boolean>;
}

export async function verifyWebhook(
  options: VerifyWebhookOptions,
): Promise<WebhookVerification> {
  if (!options.secret) throw new TypeError("secret must not be empty");
  const headers = normalizeHeaders(options.headers);
  const timestamp = headers.get("x-kila-timestamp");
  const deliveryId = headers.get("x-kila-delivery-id");
  const eventType = headers.get("x-kila-event");
  const signature = headers.get("x-kila-signature");
  const declaredVersion = headers.get("x-kila-signature-version");

  if (!timestamp || !deliveryId || !eventType || !signature) {
    return result(false, "missing_header", deliveryId, eventType);
  }
  if (declaredVersion && declaredVersion !== SIGNATURE_VERSION) {
    return result(false, "unsupported_version", deliveryId, eventType);
  }

  const issuedAtSeconds = parseTimestamp(timestamp);
  if (issuedAtSeconds === null) {
    return result(false, "invalid_timestamp", deliveryId, eventType);
  }
  const nowSeconds = Math.floor((options.now ?? new Date()).getTime() / 1000);
  const tolerance = options.toleranceSeconds ?? DEFAULT_TOLERANCE_SECONDS;
  if (!Number.isFinite(tolerance) || tolerance < 0) {
    throw new RangeError("toleranceSeconds must be a non-negative finite number");
  }
  if (Math.abs(nowSeconds - issuedAtSeconds) > tolerance) {
    return result(false, "stale_timestamp", deliveryId, eventType);
  }
  if (!signature.startsWith(`${SIGNATURE_VERSION}=`)) {
    return result(false, "unsupported_version", deliveryId, eventType);
  }

  const body = typeof options.rawBody === "string"
    ? new TextEncoder().encode(options.rawBody)
    : options.rawBody;
  const prefix = new TextEncoder().encode(
    `${SIGNATURE_VERSION}.${timestamp}.${deliveryId}.${eventType}.`,
  );
  const content = concatBytes(prefix, body);
  const expected = await hmacSha256(options.secret, content);
  const provided = signature.slice(SIGNATURE_VERSION.length + 1);
  if (!constantTimeEqual(expected, provided)) {
    return result(false, "invalid_signature", deliveryId, eventType);
  }
  if (
    options.isDeliveryProcessed &&
    await options.isDeliveryProcessed(deliveryId)
  ) {
    return result(false, "duplicate_delivery", deliveryId, eventType);
  }
  return result(true, "verified", deliveryId, eventType);
}

function normalizeHeaders(
  headers: Headers | Record<string, string | undefined>,
): Headers {
  if (headers instanceof Headers) return headers;
  const normalized = new Headers();
  for (const [name, value] of Object.entries(headers)) {
    if (value !== undefined) normalized.set(name, value);
  }
  return normalized;
}

function parseTimestamp(value: string): number | null {
  if (!/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

async function hmacSha256(secret: string, content: Uint8Array): Promise<string> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) {
    throw new Error("Web Crypto API is required to verify KilaSifen webhooks");
  }
  const key = await subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  // Copy into an owned ArrayBuffer so TS 6's SharedArrayBuffer-aware typed
  // arrays remain compatible with the Web Crypto BufferSource contract.
  const signContent = new Uint8Array(content.byteLength);
  signContent.set(content);
  const digest = await subtle.sign("HMAC", key, signContent.buffer);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function concatBytes(first: Uint8Array, second: Uint8Array): Uint8Array {
  const result = new Uint8Array(first.length + second.length);
  result.set(first);
  result.set(second, first.length);
  return result;
}

function constantTimeEqual(expected: string, provided: string): boolean {
  let difference = expected.length ^ provided.length;
  const length = Math.max(expected.length, provided.length);
  for (let index = 0; index < length; index += 1) {
    difference |= (expected.charCodeAt(index) || 0) ^ (provided.charCodeAt(index) || 0);
  }
  return difference === 0;
}

function result(
  valid: boolean,
  reason: WebhookVerificationReason,
  deliveryId: string | null,
  eventType: string | null,
): WebhookVerification {
  return { valid, reason, deliveryId, eventType };
}
