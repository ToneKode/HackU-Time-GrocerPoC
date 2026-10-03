# Time-Grocer Mock Mall (frontend)

2010s-style demo storefront for **Person 4**. Talks directly to the offline mock-api on `http://localhost:8000` (not the Person 3 agent UI).

## Run (two terminals)

```bash
# terminal 1 — mock-api
cd ../mock-api
pip install -r requirements.txt
uvicorn main:app --port 8000 --reload

# terminal 2 — frontend
cd ../frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api/*` → `http://127.0.0.1:8000/*`.

## What the UI calls

| UI action | API |
|-----------|-----|
| Boot status | `GET /health` |
| Merchant filter / rails box | `GET /merchants` |
| Catalog / search | `GET /products?q=&merchant=&category=` |
| Price Cart via API | `POST /cart` |
| Pay Now | `POST /pay` |

## Tests

```bash
npm run test:unit          # mocked fetch / pure helpers
npm run test:integration   # live frontend client + mock-api (+ DOM contract)
npm run test:all
```

Integration tests auto-start uvicorn on `:8000` if it is not already running.
