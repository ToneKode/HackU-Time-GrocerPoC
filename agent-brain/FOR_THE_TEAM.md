# What the other people need to do

Person 1 (this PR) is the shopping agent on port **8002**.

`POST /agent/intent` takes `{ "intent": "...", "monthly_spent": 0 }` and returns one ActionPlan JSON. An OpenRouter model may choose only the query, the quantity, and a sell point (`cheap`, `highest_usage`, `best_rating`). Code picks the product. The hash-chained `audit_log` is on every response.

The mall is still the JSON in `agent-brain/backend/fake_mall/` until person 4's server is up.

Person 2's check runs on every buy. The agent posts `POST /check_policy` on port 8001. If that service is down, the same caps in `policy_rules.py` decide `PASS`, `ESCALATE`, or `HALT`. The log records the result. Payment happens only after `PASS` or an approved escalation.

`frontend/index.html` is a **test counter** served at `GET /` on port 8002. Person 3 already has their own frontend. Do not replace it with this page. Someone else can wire the real UI to this JSON later.

Do not commit `agent-brain/backend/.env`. Each machine keeps its own `OPENROUTER_API_KEY`. A model id ending in `:batch` will not work on this chat endpoint. Use `deepseek/deepseek-v4.1-flash` or `openrouter/free`.

Run from `agent-brain/backend` with Python 3.13:

```powershell
py -3.13 -m pip install -r requirements.txt
py -3.13 test_agent.py
py -3.13 server.py
```

Open `http://127.0.0.1:8002` to try the test counter.

## Person 2 — policy, ledger, escalation (port 8001)

Your service is `backend-policy/` on `dev1`, port 8001. The agent already calls it.

`_budget` posts `merchant`, `category`, `amount` (the landed total), `currency` (`HKD`), `sku`, `qty`, and `monthly_spent`. Your `status` and `reason` are what the graph branches on. `rule` is kept when you return it. If the call fails, `policy_rules.py` uses the same order and the same category list.

- `POST /log_event` with `event`, `status`, `reason`. The agent posts each audit line here. If you are down, it stops retrying after the first failure and still returns its own chain.
- `POST /create_escalation` with `amount`, `currency`, `merchant`, `sku`, `qty`, `reason`. The agent calls this only after your status is `ESCALATE`.
- `GET /escalations/{id}` and `POST /escalations/{id}/decision` stay yours. You log approval, refusal, and expiry. Person 1 does not log those three again.
- `GET /audit_log` for person 3's ledger view.

Rules, first match wins: merchant blacklist, merchant not on the whitelist, category blacklist, monthly total over HK$2000, amount over HK$800, amount over HK$500 (escalate, 600 second TTL), otherwise pass. Whitelist: Watsons, HKTVmall, PARKnSHOP, Japan Home Centre. Blacklist: DarkWebMart. Category blacklist is empty, so Food, Alcohol, Electronics, and Health are allowed.

Do not let the model decide pass, halt, or pay. You do.

## Person 3 — real frontend

Keep your own app. Use `frontend/index.html` only as a sample of the request and the JSON.

Your app should call only:

- `POST http://127.0.0.1:8002/agent/intent`
- person 2's escalation routes and `GET /audit_log`, once those exist

Do not call `/products`, `/cart`, `/pay`, `/check_policy`, `/log_event`, or `/create_escalation` from the browser.

Request body: `intent` (required), `monthly_spent` (optional, default 0), `escalation_id` (optional).

Response fields: `intent`, `status`, `goal`, `product`, `quote`, `policy`, `escalation`, `payment`, `audit_log`.

New fields since `frontend/contract.json`: `product.sell_point`, and on `goal` also `sell_point`, `sku`, `thought`, `model`. `policy.status` is `PASS`, `ESCALATE`, or `HALT`. `policy.rule` names which check fired. `payment` has no reward-points field. Food, Alcohol, Electronics, and Health come back `HALTED`.

## Person 4 — mock mall (port 8000)

Your API on `dev` is the right shape. The agent is not pointed at it yet. While `MOCK_API_BASE_URL` is unset, person 1 reads `agent-brain/backend/fake_mall/*.json`.

Please:

1. Add `sell_point` to the product model in `mockup-mall/mock-api/data_loader.py` and return it from `GET /products` and `GET /products/{sku}`. Extra JSON keys are dropped today, so copying the file alone is not enough.
2. Replace `mockup-mall/mock-api/data/products.json` with the 30 products in `agent-brain/backend/fake_mall/products.json` (10 categories, 3 products each: `cheap`, `highest_usage`, `best_rating`), or add the same field to your own catalog.
3. Keep `POST /cart` as `{ "items": [{ "sku", "qty" }] }` and return `total_landed_cost`. Shipping stays HK$30 under HK$400, free at HK$400 and above, tax 0.
4. Keep `POST /pay`. You may still return `reward_points_earned`. Person 1 ignores it. `cart_total == 666` still declines with `card_declined`.

Search should match name, merchant, category, and sell point. The agent picks one sku and then calls `GET /products/{sku}`, `POST /cart`, and `POST /pay`.

## Whoever integrates

1. Start person 4 on port 8000. Set `MOCK_API_BASE_URL=http://127.0.0.1:8000` for person 1 and restart. Leave it unset to keep the fake JSON.
2. Start person 2 on port 8001 (`backend-policy`). The agent already branches on `PASS`, `ESCALATE`, and `HALT`. If 8001 is down, the local copy of those caps answers instead. Pay only after `PASS` or an approved escalation.
3. Point person 3's app at `POST /agent/intent`. Leave `frontend/index.html` as the test counter.
4. Put an OpenRouter key in `agent-brain/backend/.env`. Do not use a `:batch` model id.

## Basket — what to build next

The shared contract is `frontend/team_contract.json`. It is the one file for person 3 and person 4. A one-product buy still uses the fields already on `POST /agent/intent`. Two or more needs come back with `lines`, `repairs`, `payment_route`, `payment_reason`, and sometimes `question`.

Person 2's engine is already on the path. Every line is checked, then the landed total is checked, and each of those calls is an audit row. A swap adds `BASKET_REVISED` before the next check. Payment still happens only after `PASS` or an approved escalation.

### Person 2

- Accept `lines` on `POST /check_policy`. Each line has `merchant`, `category`, `sku`, `qty`, and `line_total`. `amount` stays the landed total. Blacklist merchants and categories per line. Apply HK$500, HK$800, and HK$2000 to `amount`.
- Until that body exists, the agent sends one check per line and one check for the total. Mixed shops use the first line's merchant on the total call. Mixed categories send a blank category on that total call, because each line was already checked.
- Do not pick products or the card.
- You still log approval, refusal, and expiry. The agent logs every `POLICY_CHECK`, including rejected baskets.

### Person 3

- Render `react` in order. Each step is Thought, Action, Observation. `source` `llm` is the model. `source` `agent` is a tool step. `source` `catalog` means the needs were built from the shelf without calling the model.
- Render `lines` with `product_reason` and `merchant_reason` when `lines` is not empty.
- Show `reply` when it is set. If some categories are blacklisted, `reply` says so, and `lines` are only the items that can still be paid.
- `status` `NEEDS_INPUT` means show `question` and wait. Do not start the approval timer and do not show a paid order.
- Show every `BASKET_PICKED`, `POLICY_CHECK`, and `BASKET_REVISED` in order. `POLICY_CHECK.result` is the policy engine snapshot (status, rule, reason, amount, monthly spend, monthly remaining, and the three caps). The hash does not cover `thought` or `result`.
- Show `payment_route` and `payment_reason`. The charged figure is `quote.total_landed_cost`. Promo savings in the reason are not subtracted yet.
- The shopper's answer goes back as a new `intent`. The agent does not yet apply "make the swap" or "send for approval".

### Person 4

- `POST /cart` may contain SKUs from more than one merchant. Keep one shipping fee on the combined subtotal. `total_landed_cost` is the number policy and pay both use.
- `POST /pay` charges `cart_total` on the `payment_route` the agent sends. You do not choose the route. Person 2 does not call you, and you do not call person 2.
- Add `sell_point` on the product model and return it. The loader still drops that key.
- Later, accept `payment_route` on `POST /cart` and return the discount plus the reduced total. Until then the agent pays the unreduced landed total.
- One pay call is one charge. Split payment across cards is not in this contract.

### Cases in that JSON

1. `mixed_merchants_pass` — cheap toilet paper (Watsons) and a cheap food container (Japan Home Centre). Landed HK$79.80. `PASS`. Paid.
2. `repick_same_sell_point` — first basket HK$520, last item has no cheaper match, an earlier line moves to the same kind of product at another shop, second check is HK$494 `PASS`. The live shelf has only one product per sell point, so this case uses a stand-in catalog.
3. `ask_before_sell_point_change` — cheap toilet paper plus two best-rated shampoos lands at HK$589.90. The agent asks before it drops the requested sell point. No payment and no escalation yet.
4. `category_halt` — toilet paper plus rice. Both are allowed. Landed HK$127.90 and paid.
5. `one_item_every_category` — one cheap item from each shelf category, including Food, Health, and Electronics. Landed HK$326.60 and paid.
6. `same_merchant` — the same ten-category list, plus one shop. HKTVmall covers every category, so the basket locks there. Landed HK$568.70, which is over the HK$500 cap, so the agent asks before anyone pays.
7. A fuzzy meal plan such as "food for 7 days with budget 700hkd" is a guess: cheap rice, water, and potato chips in week-sized quantities, landed HK$161.60. A sentence that names nothing, such as "buy me something", asks a follow-up and does not pay.
