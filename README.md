demo-admin3@example.com	

DemoAdmin3Only!


# Time-Grocer student demo

A mock shopping agent with a MySQL catalog, model-directed tools, basket optimization, approvals, recoverable mock payments and an admin market editor. No real payments are processed.

## Prerequisites and one-time setup

Use Windows PowerShell, Python 3.13, Node.js, MySQL 8, Docker Desktop (Redis), and ngrok. Replace `C:\HacKU2026` below with your checkout path if different.

```powershell
git clone https://github.com/ToneKode/HackU-Time-GrocerPoC.git C:\HacKU2026
Set-Location C:\HacKU2026
py -3.13 -m pip install -r persistance\backend\requirements.txt
py -3.13 -m pip install -r backend-policy\requirements.txt
py -3.13 -m pip install -r payment\backend\requirements.txt
py -3.13 -m pip install -r agent-brain\backend\requirements.txt
Set-Location C:\HacKU2026\frontend
npm install
```

Create the local MySQL demo database/user once with an administrator MySQL account:

```sql
CREATE DATABASE IF NOT EXISTS time_grocer CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'tg'@'localhost' IDENTIFIED BY 'tg';
GRANT ALL PRIVILEGES ON time_grocer.* TO 'tg'@'localhost';
```

The persistence service applies its MySQL schema on startup. Install Ollama and download the local tool-capable model:

```powershell
ollama pull qwen3:8b
```

Keep the Ollama app running, or run `ollama serve` in another terminal if its API is not already listening. Configure `agent-brain/backend/.env` locally if desired:

```dotenv
LLM_PROVIDER=vsakura
GATEWAY_BASE_URL=https://apisub.vsakura.top
GATEWAY_MODEL=gpt-6.1-sol
OPENROUTER_API_KEY=YOUR_GATEWAY_KEY
OLLAMA_MODEL=qwen3:8b
OLLAMA_BASE_URL=http://127.0.0.1:11434
```

The default provider is the OpenAI-compatible vsakura gateway with `gpt-6.1-sol`. `OPENROUTER_API_KEY` supplies this gateway's credential; it is not sent to OpenRouter. On a primary request failure, the same conversation continues on local Ollama for the rest of that plan, with an audited `provider_fallback` event. Each new shopping request tries the primary again. Set `LLM_PROVIDER=ollama` to use only local inference. Native `/api/chat` requests use thinking disabled, a 32,768-token context window and a 2,400 output-token cap. Local planning allows 16 model rounds and 40 tool calls, including multi-target catalog searches. Model loading or CPU inference can take several minutes; the larger context increases memory usage. Leave `USE_SCRIPTED_PLANNER` unset for model-directed planning. Keep Ollama running to support the local fallback. OpenRouter retains its economy limits.

Optional local tuning in the agent terminal or `.env`:

```dotenv
OLLAMA_NUM_CTX=32768
OLLAMA_NUM_PREDICT=2400
OLLAMA_MAX_ROUNDS=16
OLLAMA_MAX_TOOL_CALLS=40
```

If memory or speed becomes a problem, lower `OLLAMA_NUM_CTX` to `16384`. Restart the agent after changing these settings.

Start Docker Desktop and the existing MySQL Windows service:

```powershell
Get-Service MySQL80
# If stopped, use an Administrator PowerShell:
Start-Service MySQL80
Set-Location C:\HacKU2026\persistance
docker compose up -d redis
docker compose exec redis redis-cli ping
```

The demo uses **MySQL on 3306**. Start only the `redis` Compose service; the Compose file also contains an older PostgreSQL setup.

## Host each endpoint in a different terminal

Keep each terminal open. Press Ctrl+C to stop that service before starting another copy on its port. Environment variables below apply only to the terminal where you set them.

### Terminal 1: persistence, catalog, accounts and admin — 8003

```powershell
Set-Location C:\HacKU2026\persistance\backend
$env:DATABASE_URL = "mysql://tg:tg@127.0.0.1:3306/time_grocer"
$env:REDIS_URL = "redis://127.0.0.1:6379/0"
$env:PAYMENT_URL = "http://127.0.0.1:8004"
$env:DEMO_ADMIN_EMAILS = "demo-admin@example.com,demo-admin2@example.com,demo-admin3@example.com,demo-admin4@example.com"
py -3.13 -m uvicorn main:app --host 127.0.0.1 --port 8003
```

### Terminal 2: policy and approvals — 8001

```powershell
Set-Location C:\HacKU2026\backend-policy
$env:DATABASE_URL = "mysql://tg:tg@127.0.0.1:3306/time_grocer"
$env:REDIS_URL = "redis://127.0.0.1:6379/0"
py -3.13 -m uvicorn main:app --host 127.0.0.1 --port 8001
```

### Terminal 3: mock payment — 8004

```powershell
Set-Location C:\HacKU2026\payment\backend
$env:DATABASE_URL = "mysql://tg:tg@127.0.0.1:3306/time_grocer"
$env:PERSISTANCE_API_BASE_URL = "http://127.0.0.1:8003"
py -3.13 -m uvicorn main:app --host 127.0.0.1 --port 8004
```

### Terminal 4: shopping agent — 8002

Start after the first three APIs show `Application startup complete`.

```powershell
Set-Location C:\HacKU2026\agent-brain\backend
$env:PERSISTANCE_API_BASE_URL = "http://127.0.0.1:8003"
$env:POLICY_API_BASE_URL = "http://127.0.0.1:8001"
$env:PAYMENT_API_BASE_URL = "http://127.0.0.1:8004"
$env:LLM_PROVIDER = "vsakura"
$env:GATEWAY_BASE_URL = "https://apisub.vsakura.top"
$env:GATEWAY_MODEL = "gpt-6.1-sol"
$env:OLLAMA_MODEL = "qwen3:8b"
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
Remove-Item Env:MOCK_API_BASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:USE_SCRIPTED_PLANNER -ErrorAction SilentlyContinue
py -3.13 server.py
```

### Terminal 5: ngrok — public HTTPS

Configure your ngrok account once with `ngrok config add-authtoken YOUR_NGROK_TOKEN`, then start:

```powershell
ngrok http http://localhost:5173
```

Copy the HTTPS forwarding URL. The hostname may change on a new tunnel run. An assigned static domain can be selected with `ngrok http http://localhost:5173 --url https://YOUR-ASSIGNED-DOMAIN`.

### Terminal 6: frontend — 5173

Replace `YOUR-HOST.ngrok-free.app` with the hostname ngrok printed, without `https://` or a trailing slash.

```powershell
Set-Location C:\HacKU2026\frontend
$env:__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS = "YOUR-HOST.ngrok-free.app"
Remove-Item Env:VITE_AGENT_URL -ErrorAction SilentlyContinue
Remove-Item Env:VITE_POLICY_URL -ErrorAction SilentlyContinue
Remove-Item Env:VITE_PERSISTANCE_URL -ErrorAction SilentlyContinue
npm run dev
```

Open http://localhost:5173 or the ngrok HTTPS URL. Click **Visit Site** on ngrok's free first-visit page if shown. The frontend proxies `/api/agent`, `/api/policy`, and `/api/persistence`, so visitors need one tunnel. MySQL stays local. Keep your computer awake while sharing.

## Seed the catalog and demo accounts

With persistence running, use a separate setup terminal:

```powershell
Set-Location C:\HacKU2026\persistance\backend
$env:DATABASE_URL = "mysql://tg:tg@127.0.0.1:3306/time_grocer"
py -3.13 load_catalog.py C:\HacKU2026\agent-brain\backend\data\hk_products_full.json
py -3.13 seed_test_accounts.py
```

The mock admin is `demo-admin@example.com` / `DemoAdminOnly!`. Sign in, open `/admin/market`, and enter its password again to edit shared prices, merchant discounts, same-product buy-one-get-one offers, and payment rewards. See [DEMO_MARKET.md](DEMO_MARKET.md) for the presentation scenario.

Check the running APIs:

```powershell
Invoke-RestMethod http://127.0.0.1:8003/health
Invoke-RestMethod http://127.0.0.1:8001/health
Invoke-RestMethod http://127.0.0.1:8004/health
Invoke-RestMethod "http://127.0.0.1:8003/catalog/search?category=Snacks&limit=1"
```

Catalog import utilities are in `persistance/backend`; the full product JSON is in `agent-brain/backend/data/hk_products_full.json`. Imported data is shared through MySQL. Restart a backend after source or API-key changes; admin market edits apply to subsequent requests live.

## Agent workflow (ASCII)

```text
Shopper prompt + account
          |
          v
Load limits, connected methods and current market rules
          |
          v
+---------------- Model-directed planning loop ----------------+
| Model chooses a tool                                         |
|   search_catalog ---> MySQL products + total_count + paging   |
|          |                                                   |
|   optimize_basket ---> candidate policy + merchant allocation |
|          |                 discounts / delivery / rewards     |
|          |                                                   |
|   rejected agent item ---> reason ---> model picks replacement|
|          |                                                   |
|   finish_plan ---> validate searched SKUs and optimized qty   |
|                                                              |
| Every decision, tool result and failure --> durable audit    |
+--------------------------------------------------------------+
          |
          v
Price + policy checks ---> shopper basket review/edit
          |                            |
          |                 user-added item fails
          |                            v
          |                  explain and ask for review
          v
Confirm: refresh prices/rules, recheck user and account budgets
          |
          +---- above automatic cap ---> account/order approval
          |                                      |
          +--------------------------------------+
          v
Server-verified payment draft + frozen promotion snapshot
          |
          v
Shopper approves merchant payment allocations
          |
          +---- uncertain payment ---> recover SAME payment ID
          v
Captured mock payment
          |
          v
Verify capture and frozen quote; derive rewards + HK$0 gifts
          |
          +---- save failed ---> retain draft ---> retry saving
          v
MySQL order + budget + dashboard
```

Python validates calculations and policy. The normal model chooses catalog searches, revisions and tool calls. Search is bounded; the basket optimizer does not guarantee a global optimum. Audit rendering groups successful checks by stage while preserving individual failures and all original entries/hashes.

## Tests

```powershell
Set-Location C:\HacKU2026\agent-brain\backend
py -3.13 -m pytest -q
Set-Location C:\HacKU2026\persistance\backend
py -3.13 -m pytest -q
Set-Location C:\HacKU2026\payment\backend
py -3.13 -m pytest -q
Set-Location C:\HacKU2026\backend-policy
py -3.13 -m pytest -q
Set-Location C:\HacKU2026\frontend
npm run build
```

Persistence tests use a separate `time_grocer_test` MySQL database; keep demo data in `time_grocer`. PostgreSQL-only payment tests may be skipped in this MySQL setup.
