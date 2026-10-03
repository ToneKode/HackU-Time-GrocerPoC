# Mockup Mall

Person 4 workspace: mocked HKTV Mall catalog + payment rails for the HacKU Time-Grocer demo.

| Path | Role |
|------|------|
| [`mock-api/`](mock-api/) | FastAPI mock ecosystem on `:8000` |
| [`frontend/`](frontend/) | 2010s demo storefront on `:5173`, wired to mock-api |

## Quick start

```bash
# API
cd mock-api && pip install -r requirements.txt && uvicorn main:app --port 8000 --reload

# UI (separate terminal)
cd frontend && npm install && npm run dev
```

See each folder’s README for endpoints and tests.
