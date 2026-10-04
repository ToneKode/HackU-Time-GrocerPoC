# Live market demo

The admin page is `/admin/market`. Sign in with the provisioned mock account:

- Email: `demo-admin@example.com`
- Password: `DemoAdminOnly!`

Enter that password again in Market settings to load/save shared rules. Admin requests verify the database account's role allowlist and password. `DEMO_ADMIN_EMAILS` can configure the allowlist; its default is `demo-admin@example.com`. Ordinary shopper accounts cannot open the page or write through the API.

Restart persistence (8003), payment (8004), and agent (8002) after loading this implementation. Keep existing MySQL/Redis/frontend/ngrok running. Payment needs `PERSISTANCE_API_BASE_URL=http://127.0.0.1:8003`; persistence needs `PAYMENT_URL=http://127.0.0.1:8004`. No daily scraper is included.

## Present the scenario

1. Submit a shopping request and note the chosen items, merchant allocations, amount and market rule version.
2. Open Market settings in a separate admin session. Change a merchant discount threshold/percentage, add a same-product buy-one-get-one offer, or edit a catalog SKU's price.
3. Save. Submit exactly the same shopper request again. The model receives the new shared promotions and searches current MySQL prices; allocation and quote calculations use that snapshot.
4. Confirm the basket. Promotional gifts appear separately at HK$0 and cannot be edited as paid quantities. After mock payment, the dashboard shows the gift and captured amount.

Threshold discounts apply at or above the configured purchased-goods merchant subtotal before discount. Only one percentage rule per merchant is supported; percentage rules and same-SKU gifts can coexist. Gifts neither increase the subtotal nor qualify their own promotions. This demo uses a single basket delivery charge: HK$30 below HK$400 of pre-discount purchased goods. Cash cashback uses discounted goods, excluding delivery.

## Payment promotion demo

The admin payment section supports cashback, Asia Miles, membership points, and loyalty points. Cashback is entered as a percentage; miles/points are entered per HK$1 of discounted goods, excluding delivery. A blank merchant applies the rule to all merchants. Merchant-specific rates override the global rate for the same payment method and reward type. These are editable mock offers, not live bank promotions.

Suggested demo values: Mastercard 2.4% cashback and 0.1 Asia Miles per HK$1. Add a competing Visa 5% cashback to show a cashback-first shopper switch payment methods; change the shopper's benefit preference to miles to demonstrate reward ranking. An explicitly empty payment rule list disables payment rewards. Several reward types can coexist on one method.

Payment stores a server-generated market quote snapshot. Changes after draft creation apply to later quotes; captured settlement verifies the frozen quote and saves its gifts. A price/promotion change between agent quote and draft creation asks the shopper to confirm a new quote.

Successful rule checks display once per stage; failed items remain specific, with reasons and expandable evidence. Raw audit entries are retained and all original hashes verified. Agent-generated blocked candidates return to the model for replacement. A blocked product submitted in the shopper's edited basket returns for review, preserving user choice.
