import { describe, expect, it, vi } from "vitest";

import { verifyWebhook } from "../src";

const BODY = "{\"ok\":true}";
const TIMESTAMP = "1787371200";
const SIGNATURE = "v1=62f50adb68e3c2e58ddfebbe28ce79453ad190cd508c0e0c1684229b27699743";
const NOW = new Date(Number(TIMESTAMP) * 1000);

function headers(signature = SIGNATURE): Record<string, string> {
  return {
    "X-Kila-Signature-Version": "v1",
    "X-Kila-Timestamp": TIMESTAMP,
    "X-Kila-Event": "document.approved",
    "X-Kila-Delivery-ID": "del_123",
    "X-Kila-Signature": signature,
  };
}

describe("verifyWebhook", () => {
  it("verifies the exact backend HMAC signature vector", async () => {
    await expect(verifyWebhook({
      rawBody: BODY,
      secret: "whsec_test",
      headers: headers(),
      now: NOW,
    })).resolves.toEqual({
      valid: true,
      reason: "verified",
      deliveryId: "del_123",
      eventType: "document.approved",
    });
  });

  it("rejects tampered raw bytes", async () => {
    const verification = await verifyWebhook({
      rawBody: "{\"ok\": true}",
      secret: "whsec_test",
      headers: headers(),
      now: NOW,
    });

    expect(verification).toMatchObject({ valid: false, reason: "invalid_signature" });
  });

  it("rejects stale signatures before replay processing", async () => {
    const replayLookup = vi.fn(() => false);
    const verification = await verifyWebhook({
      rawBody: BODY,
      secret: "whsec_test",
      headers: headers(),
      now: new Date(NOW.getTime() + 301_000),
      isDeliveryProcessed: replayLookup,
    });

    expect(verification.reason).toBe("stale_timestamp");
    expect(replayLookup).not.toHaveBeenCalled();
  });

  it("supports an asynchronous persistent replay lookup", async () => {
    const verification = await verifyWebhook({
      rawBody: new TextEncoder().encode(BODY),
      secret: "whsec_test",
      headers: new Headers(headers()),
      now: NOW,
      isDeliveryProcessed: async (deliveryId) => deliveryId === "del_123",
    });

    expect(verification).toMatchObject({ valid: false, reason: "duplicate_delivery" });
  });

  it("reports missing headers without parsing the body", async () => {
    const verification = await verifyWebhook({
      rawBody: "not-json",
      secret: "whsec_test",
      headers: {},
      now: NOW,
    });

    expect(verification).toEqual({
      valid: false,
      reason: "missing_header",
      deliveryId: null,
      eventType: null,
    });
  });
});
