# Mock API — HacKU Time-Grocer

Offline FastAPI stand-in for HKTV Mall catalog + a payment gateway. No live sites are scraped; all data is loaded from local JSON at startup.

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
uvicorn main:app --port 8000 --reload
```

Server listens on `http://localhost:8000`.

## Tests

```bash
pytest -q
```

Covers health, product filters, cart shipping/TLC rules, payment success/decline, idempotency, and the ~500ms `/pay` delay.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness check |
| GET | `/products` | List/filter products (`q`, `merchant`, `category`) |
| GET | `/products/{sku}` | Single product (404 if missing) |
| GET | `/merchants` | Whitelist / blacklist |
| POST | `/cart` | Price cart (shipping, TLC) |
| POST | `/pay` | Simulate payment + rewards (~500ms) |

### Example curls

```bash
curl http://localhost:8000/health

curl "http://localhost:8000/products?q=toilet"

curl http://localhost:8000/products/SKU001

curl http://localhost:8000/merchants

curl -X POST http://localhost:8000/cart \
  -H "Content-Type: application/json" \
  -d '{"items":[{"sku":"SKU001","qty":1}]}'

curl -X POST http://localhost:8000/pay \
  -H "Content-Type: application/json" \
  -d '{"cart_total":89.9,"payment_route":"mastercard","idempotency_key":"demo-1"}'
```

## Notes

- `cart_total == 666.00` on `/pay` forces `card_declined` for demo failure paths.
- Reusing the same `idempotency_key` after a successful `/pay` returns the same `order_id`.
- CORS is permissive so the frontend on `:5173` can call this service directly.
