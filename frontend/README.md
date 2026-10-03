# Frontend — HacKU Time-Grocer (Person 3)

Vue 3 + Vite grocery price-comparison app (in the style of arzan.kz) with an agent checkout.
The agent spec is [`contract.json`](contract.json).

## Pages

| URL | What it shows |
|-----|---------------|
| `/` | Hero, category shortcuts, "Mega deals" with store filter |
| `/catalog` | Category sidebar, store chips, sorting, search results (`?q=`, `?category=`) |
| `/cart` | **Optimal mix** (each item at its cheapest store) and **One store** comparison; checkout button is a placeholder for the agent |
| `/agent` | Chat with the shopping agent: replies carry the order, the approval card (10-minute timer) and the steps; budget, rules and settings in a sidebar (drawer on phones) |

## Run

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

## Mock vs live

By default the app uses a **fake backend in the browser** (`src/lib/mock.js`), built from the
contract's examples, so every screen works before the agent and policy services exist.

To call the real services, create `frontend/.env.local`:

```
VITE_USE_MOCK=false
VITE_AGENT_URL=http://localhost:8002
VITE_POLICY_URL=http://localhost:8001
```

## Where things are

| File | What it does |
|------|--------------|
| `src/data/catalog.js` | Demo products, stores and categories (prices per store, HKD) |
| `src/lib/pricing.js` | Cheapest offer, optimal mix, single-store totals, savings |
| `src/stores/auth.js` | Log-in session. **Not connected to a server yet:** keeps only name/email/phone in the browser, never the password. Replace `logIn`/`register` with the accounts API |
| `src/stores/shop.js` | Cart + favourites (saved in localStorage) |
| `src/views/` | One file per page |
| `src/content/` | About page and legal documents (Terms, Return Policy, Privacy Policy) in all three languages. **Drafts: have a Hong Kong solicitor review before launch.** Update `LEGAL_UPDATED` in `index.js` when you change them |
| `src/i18n/` | Translations: `en.js`, `zh-Hant.js` (繁體), `zh-Hans.js` (简体) for UI text; `products.js` for product and store names |
| `src/components/shop/` | Header, product card, store chips, qty stepper |
| `src/views/AgentView.vue` | Agent chat: messages, sends the intent, polls the escalation every second, handles Approve/Refuse |
| `src/lib/api.js` | The only four calls the frontend makes (`contract.json` → `calls`) |
| `src/lib/mock.js` | Fake agent + policy API for local work |
| `src/lib/hash.js` | Checks the audit log's sha256 hash chain in the browser |
| `src/components/` | Cards shown inside the agent chat and its sidebar |

## Agent demo scenarios (`/agent`)

- **Normal order:** "Buy toilet paper" with HK$0 spent. Shows *Order placed* (HK$119.90).
- **Monthly cap hit:** the same intent with HK$1,900 spent. Shows *Halted*.
- **Bulk:** "Buy bulk toilet paper". Shows *Needs your approval* and a 10:00 timer. Approve completes the order; Refuse cancels it.

## Languages

English, 繁體中文 and 简体中文. Switch from the ☰ menu → Language. The choice is saved in the browser;
the first visit follows the browser language. To add a string, add the same key to all three files in
`src/i18n/` and use `$t('section.key')` in templates. The `/agent` demo page is English only.
