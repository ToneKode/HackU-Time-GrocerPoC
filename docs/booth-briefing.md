# Grocer booth briefing

Internal only. HackU 2026, HKT challenge **Give a Machine a Wallet — Agentic Commerce**.

Read this before a judge or visitor asks a question. The public product name on the demo is **Grocer**. The repo is Time-Grocer. Payments in the demo are mock. No real card is charged.

Live demo: https://7b83-118-140-62-215.ngrok-free.app/

If ngrok shows a warning page, click **Visit Site**. The hostname can change when the tunnel restarts. The shop and its APIs share that one address.

---

## Say this first

A household shopper delegates one decision to Grocer: **which groceries to buy, from which of four Hong Kong shops, on which connected card, inside a spending limit the shopper set.**

The agent may search, compare, build a basket, and prepare a payment. It may not decide that a payment is allowed. Python checks the basket against written rules. If a rule says stop, nothing is captured.

The model chooses searches and quantities. It does not choose pass, halt, or pay.

---

## The scope we picked

The problem statement asks for one spending decision and one party delegating it.

| Piece | Our answer |
|---|---|
| Spending decision | A grocery basket in HKD across Watsons, HKTVmall, PARKnSHOP, and Japan Home Centre, including the HK$30 delivery fee when it applies. |
| Who delegates | The signed-in shopper. They write the shopping sentence and own the account limits, connected cards, and reward ranking. |
| Mandate | Profile caps plus a fixed rule list. A shopping sentence is a request, not a blank cheque. A maximum written in the sentence (“budget 700”) is also enforced at confirm. |
| What “stopped” looks like | The agent returns the basket for editing, asks for a 10-minute approval, or refuses the payment. Capture does not run. |

We did not build a chain where person A authorises person B who authorises person C.

---

## What the agent may do

- Search the MySQL catalog and page through results. A SKU can enter the basket only if a search returned it.
- Compare the same kind of product across the four shops.
- Build a multi-item basket, including a meal plan when the sentence names days, people, or a food budget.
- Rank a **connected** card for each shop using the shopper’s reward order.
- Apply the current shared market rules: merchant percent-off, same-SKU buy-one-get-one gifts at HK$0, and payment rewards.
- Explain each line from the recorded rule, price, and card.
- Prepare a one-time scoped payment draft and capture it only after the shopper approves.
- Write every step to a SHA-256 hash-chained log.

## What the agent may not do

- Pass, halt, or pay because the model “thinks it is fine.”
- Buy from a shop that is not on the whitelist. **DarkWebMart** is blocked by name.
- Spend above the bulk ceiling, or above the monthly cap.
- Treat a product description, photo, or review as an instruction to ignore the budget.
- Invent a Hong Kong dollar value for points or miles.
- Split one basket across two cards for the same shop, use FPS, BNPL, or a foreign currency.
- Store a full card number or CVV. Demo methods are labels and last-four only.
- Charge twice when a payment looks uncertain. Recovery reuses the same payment id.

## How the limit is actually enforced

The policy service (`backend-policy`, port 8001) evaluates in this order. **First match wins.** The same order is copied in the agent so a dead policy service still returns pass, escalate, or halt.

1. Merchant blacklisted → **HALT**
2. Merchant not on the whitelist → **HALT**
3. Category blacklisted → **HALT** (the default category list is empty)
4. This month’s spend plus this basket over the monthly cap → **HALT** (default **HK$2,000**)
5. Landed total over the bulk ceiling → **HALT** (default **HK$800**)
6. Landed total over the per-order automatic cap → **ESCALATE** (default **HK$500**, 600-second approval)
7. Otherwise → **PASS**

The amount checked is `total_landed_cost`: goods plus delivery (tax is 0 in this demo). A merchant discount and cashback do **not** raise the cap. Cashback is reported after the check.

On confirm:

- **HALT** does not pay. The basket comes back as “I need a change” so the shopper can remove a line. A blocked product the shopper added themselves is sent back for review. The agent does not silently swap it.
- **ESCALATE** opens a 10-minute approval. Approve continues. Refuse cancels. If nobody answers, the timer expires and a late click is ignored and logged.
- A maximum in the shopper’s own sentence (`user_max_total`) stops confirm even when the standing caps would pass.
- Delivery can be the thing that crosses the line. One basket-wide fee: **HK$30** when pre-discount goods are under **HK$400**, free at HK$400 and above. Example: HK$480 of goods plus HK$30 delivery is HK$510, which waits for approval.

A second gate sits on the payment itself. A charge of HK$400 or more is flagged for an extra confirmation even when policy would pass. That is risk step-up, separate from the HK$500 approval.

Shopper profile caps override the defaults when the person is logged in. The standing rules are still code. The model cannot edit them.

---

## Demo, in this order

Stay on **Agent** (`/agent`) for the story. Use Catalog only if someone asks where prices come from.

### 1. The rules, before any purchase

The right-hand panel already shows the mandate:

- Monthly cap HK$2,000, spent, and remaining
- Automatic limit per order HK$500
- Maximum with approval HK$800
- Time to approve 10:00
- Allowed stores: Watsons, HKTVmall, PARKnSHOP, Japan Home Centre
- Blocked store: DarkWebMart

Say: “These numbers are the mandate. The chat box is only the shopping request.”

### 2. One complete transaction

Click **cheap toilet paper**.

Walk the result in this order:

1. The basket and the shop it chose.
2. **Why this item** — price, sell point, and the next similar row.
3. The card and the sentence that says why that card.
4. Delivery, if the goods are under HK$400.
5. Approve the payment sheet. The capture is mock.
6. Open **Show steps**. The hash line should read verified.

That is the end-to-end purchase: request, priced basket, policy pass, human approval of the draft, mock capture, log.

### 3. Show it being stopped

Do **one** of these. Do not stack them in front of a judge.

**Refusal or expiry (best booth stop).** Send a request whose landed total should land between HK$500 and HK$800, for example **buy food for 7 days with budget 700hkd**. When the approval card appears, click **Refuse**. Say: “The timer is 10 minutes. Refuse, or silence, both end in no charge. A click after expiry is logged as ignored.”

**Hard halt.** In **Already spent this month**, enter `1900`, then send **cheap toilet paper**. The monthly cap stops the purchase. Nothing is charged. Set the field back to `0` afterwards so the next demo still works. Logged-out, that field is for the session. Logged-in, monthly spend is the account’s recorded spend.

**Shopper’s own sentence.** A meal plan that quotes above the maximum in the sentence comes back for edits. The policy engine can say pass and the confirm step still refuses to pay.

**Unknown shop.** The whitelist halt is real, but the live catalog does not sell from DarkWebMart. Describe the rule and point at the red chip. Do not pretend you just bought from a blocked shop unless that row is actually in the catalog.

### 4. Same basket, different reward

If you are logged in as a shopper with more than one connected method:

- Rank **cashback** first and run a prompt.
- Rank **Asia Miles** first and run the same prompt.

The card can change. Points do not get a made-up dollar price. They win only because the shopper ranked them first, and only when the item is inside a close price band: the cheapest similar row, plus **HK$3 or 8%**, whichever is larger. A big reward on a much more expensive item does not jump the queue.

### 5. Market rules, only if you have a minute and can revert

`/admin/market` needs an admin account and the password typed again on that page.

Change one merchant percent or one payment reward, save, and send the **same** prompt again. The new quote uses the new snapshot. A change after a draft is created does not rewrite that draft. The shopper is asked to confirm a new quote.

Revert the rule before you leave the booth.

---

## Why it did that

Answer from the step list, not from a story you invent after the fact.

Each audit row has an event, a status, a reason, and a hash tied to the previous row. The UI checks the chain in the browser. `thought` is shown and is **not** part of the hash. The hashed fields are the event, status, and reason.

Useful event names:

| Event | Meaning |
|---|---|
| INTENT_RECEIVED | The shopping sentence arrived |
| PLAN / SEARCH | What the model asked to look up |
| BASKET_PICKED / BASKET_REVISED | A basket was chosen or a line was swapped |
| POLICY_CHECK | The rule that fired, the amount, and the caps |
| ESCALATION_CREATED / APPROVED / REFUSED / EXPIRED | The human gate |
| PAYMENT | Capture was attempted |
| HALTED | Stopped before payment |

If the chain says broken, say so. There is a demo tamper endpoint for that story. Do not tamper the live booth database unless you can reset it.

The payment record is a separate evidence pack: rail, amount, risk score, and whether step-up was confirmed. The pack does not include the raw token.

---

## Payment and what a reward is worth

Connected demo methods:

| Method | Demo reward written in code | When it is used |
|---|---|---|
| Mox Mastercard | 2.4% cashback, and 1 membership point per HK$1 of discounted goods (2× at Watsons in the fallback table) | Default when the shopper has not saved cards |
| Alipay | 0.25 loyalty points per HK$1 | Only if that method is connected |
| ICBC Visa | 0.125 Asia Miles per HK$1 | Only if that method is connected |

Say this sentence if anyone asks whether those rates are live bank rates:

**“Those three rates are demo constants in `agent-brain/backend/benefits.py`, so the booth can show ranking. They are not a feed we pulled from Mox, Alipay, or ICBC today. An admin market snapshot replaces them for the next quote. Cashback is the only reward we subtract from the effective cost. We do not convert points or miles into dollars.”**

Fallback shop offers, used only when no market snapshot is loaded:

- Watsons: 15% off when goods are at least HK$300
- PARKnSHOP: 10% off when goods are at least HK$300

If a snapshot is loaded, those fallbacks are not applied. The snapshot’s own percent and gift rules are.

There is also a research file, `agent-brain/backend/hk_retail_promos_20261003.json`, collected **2026-10-03 14:30 HKT**. It lists public Watsons, HKTVmall, PARKnSHOP, and Japan Home Centre offers. Many rows have unconfirmed dates and secondary sources. An older helper and the payment recommender can read it. **Do not quote a row from that file as the rate on a captured order** unless that exact rule is in the market snapshot the checkout froze.

Shipping rule to memorise: **HK$30 under HK$400 of pre-discount goods, otherwise HK$0.** Gifts are HK$0 and do not count toward the threshold.

Payment states: `DRAFT → AUTHORIZED → CAPTURED`, or `FAILED` / `REFUNDED`. The draft is a one-time scoped token (merchant, amount, currency, purpose, expiry). A mock rail still declines a cart total of **666.00**.

If capture succeeds and saving the order fails, the draft is kept and **Retry saving order** writes the budget and the dashboard. Do not start a second payment.

---

## The “4 min vs 10 sec” card

The Agent sidebar says manual checkout is **4 min, 15 steps** and agent checkout is **10 sec, 1 step**. Those figures are stored in `frontend/contract.json`. They are a product illustration, not a stopwatch study.

If a judge asks, say that plainly, then describe the manual path in words:

1. Open Watsons, HKTVmall, PARKnSHOP, and Japan Home Centre.
2. Search each item in each app.
3. Compare the basket, including delivery.
4. Pick a card and a reward.
5. Check out, and check the cap yourself.

The agent path is one sentence, a reviewed basket, and one approval. The time card is a picture of that difference. It is not measured evidence.

---

## Pages a visitor might open

| Page | What to say |
|---|---|
| `/` | “Compare the whole basket, then let the agent check out.” Deals show the same product at more than one shop. Yellow badges are the discount versus the higher shelf price. |
| `/catalog` and `/product/:id` | Price comparison, not the agent. The product page can show a price history chart. |
| `/cart` | Optimal mix versus one-store total. Checkout with the agent is the `/agent` flow. |
| `/agent` | The booth. |
| `/profile` | Logged-in caps, connected methods, and reward rank. |
| `/dashboard` | Paid mock orders, gifts, and how often policy stopped a run. |
| `/admin/market` | Shared prices and promotions. Admin only. |
| `/about`, `/terms`, `/returns`, `/privacy` | Draft copy. Say a Hong Kong solicitor has not signed them off. The about page states the same caps. |

Languages: English, 繁體中文, 简体中文, from the menu. Light, dark, and system theme. The booth should stay on **light**, because that is the look of the pitch.

---

## Questions we should expect

**Is this a real payment?**
No. It is a mock rail with a real control loop: scoped token, authorize, capture, evidence. HKT’s topic was the control loop, not a live acquirer.

**Who holds the loss if the agent is wrong?**
In this demo, nobody is charged. A stop happens before capture. If a mock capture is saved and the order row fails, we keep the draft and retry the save. A refund API exists. The booth does not have a refund screen, and we do not demo unwinding a reward.

**Can the agent be talked into ignoring the cap?**
The shopping sentence can name items and a maximum. It cannot change the policy order. Product text is catalog data. Adversarial prompts live in `agent-brain/ADVERSARIAL_TEST_PROMPTS.md`. We do not run hostile listings on the public booth catalog.

**Does it always find the cheapest basket?**
No. Search is bounded. The optimizer compares merchant allocations for fixed quantities and says when it hit its search limit. It does not promise a global optimum, and it does not split one line across shops.

**What if the model picks a bad product?**
The shopper sees the basket before capture and can swap or remove a line. A swap is checked again. The reason on the line is generated from the catalog row and the rule, then checked so the model cannot attach a number that was not in the input.

**What expires?**
The approval, after 600 seconds. There is no separate “mandate document” with its own renewal ceremony. Changing caps in Profile is how a person tightens or relaxes the standing limits.

**What is logged for a third party?**
The hash chain. They can recompute it without trusting our explanation. They still trust that we appended the rows. A tamper flips `valid` to false. That is the claim: edits show up. It is not a public blockchain.

---

## Do not claim these

- A non-programmer wrote the enforceable policy as a free-text sentence. The sentence is the shopping request. The enforceable policy is the ordered rule list and the profile caps.
- Delegation from A to B to C, or a velocity stop such as “five purchases in ten minutes.”
- A revocation that arrives in the middle of a live acquirer call. What we have is refuse, expiry, and “late decision ignored.”
- Live FX, FPS, BNPL, or split tender.
- That every cashback figure on screen was observed from a bank on a timestamp.
- That 4 minutes and 15 steps were measured.
- That the legal pages are final.

---

## If the demo breaks

- ngrok warning page: **Visit Site**.
- Agent spinner that never ends: the model or port 8002 is stuck. Use the three suggestion chips. Do not retype a long prompt over and over.
- “Something went wrong” on send: say the agent service is unreachable and show the rules panel and the catalog. Do not invent a basket.
- Wrong prices after an admin edit: that is the point of the market page. Revert, or say which version you changed.
- Payment looks uncertain: use **Check payment status**. Do not click pay again.

Services, if someone technical asks: persistence 8003 (accounts, catalog, orders), policy 8001, agent 8002, mock payment 8004, shop on 5173. MySQL database `time_grocer`. The browser only talks to the shop, which proxies the APIs.

---

## Booth login

Use the account provisioned on the **running** demo:

- Email: `demo-admin4@example.com`
- Password: `DemoAdmin4Only!`

That account is for the live tunnel. The repo’s seed script still documents a different mock admin, `demo-admin@example.com` / `DemoAdminOnly!`. If the live login fails, the process environment `DEMO_ADMIN_EMAILS` is the allowlist that matters.

Do not put either password on a slide, a poster, or a public chat.

Two extra shopper accounts exist only if `seed_test_accounts.py` was run:

- `test-3methods@example.com` / `TestShopper3!` — Mastercard, Alipay, and Visa, cashback first
- `test-2methods@example.com` / `TestShopper2!` — Alipay and Visa, Asia Miles first

They are for the reward-ranking demo. They are not required for the stop demo.
