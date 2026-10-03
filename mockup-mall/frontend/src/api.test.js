import { beforeEach, describe, expect, it, vi } from "vitest";
import { createApi } from "./api.js";

describe("createApi", () => {
  let fetchMock;
  let client;

  beforeEach(() => {
    fetchMock = vi.fn();
    client = createApi("http://mock-api.test", fetchMock);
  });

  it("getHealth hits /health", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    await expect(client.getHealth()).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://mock-api.test/health",
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });

  it("getProducts builds query string", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify([{ id: "SKU001" }]), { status: 200 }),
    );
    await client.getProducts({ q: "toilet", merchant: "Watsons" });
    const url = fetchMock.mock.calls[0][0];
    expect(url).toContain("/products?");
    expect(url).toContain("q=toilet");
    expect(url).toContain("merchant=Watsons");
  });

  it("getProduct encodes sku path", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ id: "SKU001" }), { status: 200 }),
    );
    await client.getProduct("SKU001");
    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://mock-api.test/products/SKU001",
    );
  });

  it("postCart sends items JSON", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          total_landed_cost: 119.9,
          shipping_fee: 30,
          subtotal: 89.9,
        }),
        { status: 200 },
      ),
    );
    const body = await client.postCart({
      items: [{ sku: "SKU001", qty: 1 }],
    });
    expect(body.total_landed_cost).toBe(119.9);
    const init = fetchMock.mock.calls[0][1];
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      items: [{ sku: "SKU001", qty: 1 }],
    });
  });

  it("postPay includes optional idempotency_key", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({ success: true, order_id: "ORD-abcd1234" }),
        { status: 200 },
      ),
    );
    await client.postPay({
      cart_total: 89.9,
      payment_route: "mastercard",
      idempotency_key: "k1",
    });
    const init = fetchMock.mock.calls[0][1];
    expect(JSON.parse(init.body)).toEqual({
      cart_total: 89.9,
      payment_route: "mastercard",
      idempotency_key: "k1",
    });
  });

  it("throws with status on HTTP errors", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: "Unknown SKU: NOPE" }), {
        status: 404,
      }),
    );
    await expect(client.getProduct("NOPE")).rejects.toMatchObject({
      message: "Unknown SKU: NOPE",
      status: 404,
    });
  });
});
