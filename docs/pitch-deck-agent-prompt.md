# Prompt: build the Grocer pitch deck

Copy everything below the line into a new agent. Do not attach the booth passwords. The deck is for judges and visitors. The briefing next to this file is internal.

---

You are building a pitch deck for **Grocer**, a HackU 2026 project for HKT’s challenge **Give a Machine a Wallet — Agentic Commerce**.

Build a real Google Slides presentation. Do not write a Markdown outline and stop. Do not build the deck in Figma, Keynote, or PowerPoint unless Google Slides is unavailable after you have tried the skill and the MCP tools below.

## Skills you must load before any slide

1. Read and follow, in full, the Google Slides skill:
   `$HOME/.cursor/plugins/cache/cursor-public/45893415/e43c7ee26e0038c6c1fa8380dd34ce86ff94cb2a/skills/google-slides/SKILL.md`
   If that path is missing, locate the installed `google-slides` skill and read that file. Discover the Google-slides MCP tool schemas with `GetDynamicTools` before the first call. Compose each slide with the same theme. Read every compose reply for overflow and overlap. Render a large thumbnail of every slide and look at it. Fix contrast, crowding, and wrapping before you finish. Export a PDF through the Google Drive skill if it is available (`google-drive` skill and `google_drive_export_file`) so the team can present offline.

2. Read the internal source of truth before you invent a claim:
   `docs/booth-briefing.md` in the Grocer repo (HackU-Time-GrocerPoC).
   If you can open the repo, also skim `README.md`, `DEMO_MARKET.md`, `backend-policy/policy_engine.py`, and `agent-brain/backend/benefits.py`. The briefing wins if a comment elsewhere is older.

3. Look at the live shop before you choose colors. Open https://7b83-118-140-62-215.ngrok-free.app/ and https://7b83-118-140-62-215.ngrok-free.app/agent (send header `ngrok-skip-browser-warning: 1`, or click through the ngrok interstitial). Use a screenshot of the light theme. If the tunnel is down, use the tokens in this prompt. Do not restyle the product.

## What the deck has to make a judge believe

One household shopper delegates one decision: which groceries to buy, from which of four Hong Kong shops, on which connected card, inside a limit the shopper set.

Grocer may search, compare, build the basket, and prepare payment. It may not decide that payment is allowed. A Python policy engine, first match wins, stops the agent. The model never passes, halts, or pays.

Show one complete mock transaction and one stop. Show that “why” comes from the recorded rule and a hash-chained log, not from a paragraph written afterwards.

## Facts you may use

- Product name on the site: **Grocer**. Wordmark is lowercase, with a shopping-bag mark.
- Tagline already on the site: **Compare the whole basket and let the agent check out.**
- Shops: Watsons, HKTVmall, PARKnSHOP, Japan Home Centre. Blocked example: DarkWebMart.
- Currency: HKD. Tax in the demo is 0.
- Delivery: HK$30 when pre-discount goods are under HK$400, otherwise HK$0. One fee for the basket.
- Default mandate, in order: blacklist, whitelist, category blacklist (empty), monthly cap HK$2,000, bulk ceiling HK$800, per-order automatic cap HK$500 then a 10-minute human approval, else pass.
- The checked amount is landed cost, goods plus delivery. Discounts and cashback do not raise the cap.
- A maximum written in the shopping sentence is enforced again at confirm.
- Cards the demo knows: Mox Mastercard, Alipay, ICBC Visa. The shopper connects them and ranks rewards. Cashback is the only reward converted into dollars. Points and miles are not given an invented HKD value. A reward can change the pick only inside HK$3 or 8% of the cheapest similar item.
- Demo instrument rates, label them **demo constants, not a live bank feed**: Mastercard 2.4% cashback and 1 membership point per HK$1 (2× at Watsons only in the fallback table); Alipay 0.25 loyalty points per HK$1; ICBC Visa 0.125 Asia Miles per HK$1. Fallback shop offers when no admin snapshot is loaded: Watsons 15% off from HK$300, PARKnSHOP 10% off from HK$300.
- A research file of public offers was saved at **2026-10-03 14:30 HKT**. Many dates are unconfirmed. Do not present those offers as the rate on a captured payment.
- Payment is a mock control loop: scoped one-time token, draft, authorize, capture, evidence pack. A total of 666.00 is a scripted decline. No PAN or CVV is stored.
- The manual-versus-agent card in the product (4 min / 15 steps versus 10 sec / 1 step) is an illustration stored in the frontend contract. You may show the contrast as an illustration. You must say it was not a timed study. You may list the real manual steps: four shop apps, search each item, compare delivery, pick a card, check out, watch the cap yourself.
- Languages on the site: English, Traditional Chinese, Simplified Chinese. The deck itself should be English.

## Facts you must not use

- Do not say a free-text sentence is the enforceable mandate. The sentence is the shopping request.
- Do not say we built person-to-person delegation chains, a velocity limit, FPS, BNPL, FX, or split pay.
- Do not say a live acquirer was revoked mid-call. The stop we can show is halt, refuse, or a 10-minute expiry, plus a late decision that is ignored and logged.
- Do not say the basket optimizer is a global optimum.
- Do not invent fees, cashback percentages, point values, timings, or user counts.
- Do not put demo passwords, API keys, or the admin email password on a slide.
- Do not claim the Terms, Privacy, or Return pages have been reviewed by a solicitor.
- Do not use a dark fintech palette, neon, or a purple gradient. The shop is a light grocery product.

## Aesthetics — match the website, light theme

The judges will look at the site and then the deck. The deck should feel like the same product.

Observed from the live light theme and `frontend/src/shop.css`:

- Canvas: `#F3F6FB` (cool gray-blue). Not pure white for the slide background, and not navy.
- Cards: `#FFFFFF`, with a hairline close to `#E3E8F0` and a soft shadow. Corner radius about 16–20 pt on cards, fully round pills for buttons.
- Primary action blue: `#3D6EF0`. White text on that blue. Soft blue fills: `#E6EDFD`.
- Price and success green: `#1F9D6B`. Use green for money and for “allowed” or “captured.”
- Deal badge yellow: `#FFD84A` with ink `#3A2F00`. Use it sparingly, the way the site uses a discount chip.
- Body text: `#1C2321`. Titles are heavy, tight, and almost black. The hero’s second line is the primary blue.
- Muted site gray `#6B7470` is too light for small slide text. Run `check_contrast`. Prefer a darker secondary near `#444746` on white and on `#F3F6FB`.
- Danger, if you show a stop: `#B3261E` on a pale `#FBE6E4` chip. Do not fill a whole slide red.
- Type: a plain grotesque. The site uses system-ui / Segoe UI / Roboto. In Slides use Inter, Arial, or the closest clean sans. No serif headlines, no monospace deck. The only mono is a short hash or rule id, if you show one.
- Layout: lots of air, a left-heavy headline, white cards, one idea per slide. The homepage is a big sentence beside a cluster of soft category tiles, then a deal row. Echo that. Do not use a dense consulting grid.
- Wordmark on the title slide: lowercase **grocer**, bold, with a simple bag mark or the word alone. Do not rename it Time-Grocer on the title.

Pass this palette as the same `compose_slide` theme on every slide. Map roles to these colors: background `#F3F6FB`, surface `#FFFFFF`, primary `#3D6EF0`, text `#1C2321`. After `check_contrast`, darken any secondary text that fails. Keep yellow as a chip, not as a text color on white.

## Slide list

Build these 12 slides, in this order. Speaker notes on every slide, two to four sentences the presenter can say. Notes may be more careful than the slide. The slide stays short.

1. **Title.** grocer. Subtitle: Give a machine a wallet. One line: a household grocery agent that can shop and pay only inside a limit a person set. HackU 2026 · HKT. No passwords.

2. **The pain.** One basket, four Hong Kong shops, one card decision, and no safe way to hand that to an agent. The pain is not “search is hard.” The pain is delegated spend.

3. **The decision we scoped.** Who delegates: the shopper. What they delegate: the grocery basket, the shop, and the connected card. What they keep: the cap, the whitelist, and the approval.

4. **May / may not.** Two columns. May: search, compare, propose a basket, rank a connected card, prepare a draft. May not: pass, halt, or pay; leave the whitelist; ignore the monthly cap; treat a product description as an instruction.

5. **The rule that actually stops it.** The ordered list: blacklist, whitelist, category, HK$2,000 month, HK$800 hard stop, HK$500 then a person, else pass. Say first match wins, and the model is not in this list. Mention that delivery is inside the amount, so HK$30 can be what crosses HK$500.

6. **One transaction.** A simple flow: sentence → basket with reasons → policy pass → shopper approves the draft → mock capture → hash-chained log. Use the toilet-paper path as the example. Do not paste a fake order total.

7. **The stop.** Three outcomes, one slide: under HK$500 can proceed to approval of the draft; HK$500 to HK$800 waits 10 minutes and dies on refuse or silence; over HK$800 or over the month never captures. A late approval after expiry is ignored and logged.

8. **Why it did that.** The answer is the audit row: event, rule, amount, previous hash. Thought text is visible and is not hashed. A third party can recompute the chain. Say what that does not prove: it proves the log was not edited, not that a bank settled.

9. **What a reward is worth.** Ranking: the shopper’s order, cash first or miles first. Cashback changes effective cost. Points and miles do not get a dollar price. Close-price band: HK$3 or 8%. Label the 2.4%, 0.25, and 0.125 figures as demo constants.

10. **The same basket, the manual way.** Left: the real steps a person takes across four shops. Right: one sentence and one approval. If you show 4 min / 15 steps and 10 sec / 1 step, the caption must say “illustration, not a timed study.”

11. **What we are honest about.** Mock rails. No delegation chain. No velocity limit. Optimizer is bounded. Public promo notes from 3 Oct 2026 are research, not the captured rate. This honesty is a feature. Judges were told fabrications count as fabrications.

12. **Close.** Repeat the mandate in one sentence: the agent shops, the rule pays. Invite them to the booth to see a pass and a refuse on the live Grocer site. Do not print the URL if it is an ngrok address that will rot; say “the Grocer booth demo” unless the team gives you a stable URL.

## How to work

- Create the presentation, then compose slide by slide.
- Put the presenter script in speaker notes, not in tiny footer text.
- After the thumbnails look right, reply with the Slides URL, the PDF link if you exported one, and a list of any claim you almost made and then cut because it was not in the briefing.
- If Google Slides auth fails, authenticate that MCP and continue. Do not switch tools before that.
- If you need a second visual reference, screenshot the live homepage and the Agent page. Match those, including the blue accent line and the yellow discount chip. Do not copy product photos into the deck unless you generated or exported them yourself. Prefer simple cards and short words over screenshots crammed onto a slide.
