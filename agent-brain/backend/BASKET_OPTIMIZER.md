# Python basket optimizer tool

`basket_optimizer.optimize_basket` compares merchant allocations for fixed product quantities. It uses existing `benefits.settlement_for` merchant promotions and connected payment methods. It does not call an LLM, approve an order, or charge a payment.

The agent registers the account-aware adapter in `ShoppingAgent.tools['optimize_basket']` and exposes its schema in `ShoppingAgent.tool_schemas`. Meal planning invokes the Python optimizer for its candidate baskets. Ordinary multi-item planning invokes the adapter after fitting unless the shopper explicitly assigned individual needs to merchants. Edited checkout baskets remain subject to the existing confirmation and policy checks.

## Account-aware API

```http
POST /agent/basket/optimize
Content-Type: application/json

{
  "account_id": "YOUR_MOCK_ACCOUNT_ID",
  "intent": "buy these items under HK$700",
  "lines": [{"sku": "SKU_FROM_CATALOG", "qty": 1}]
}
```

Via the frontend/ngrok proxy, use `/api/agent/agent/basket/optimize`. The adapter loads catalog prices and the account's payment methods itself. The result contains `lines`, `quote`, `settlement`, and `optimization` metadata. `optimization.feasible` must be checked before accepting the proposed allocation. The optimizer endpoint does not create a payment draft; checkout still goes through basket confirmation.

## Python API

```python
from basket_optimizer import optimize_basket

result = optimize_basket(
    lines, catalog, methods=connected_cards, rank=benefit_rank,
    max_total=500, min_total=400, shipping=(400, 30),
)
```

`candidate_sets`, if supplied, align with lines and contain approved alternative catalog IDs or records. Such callers must establish product equivalence; known pack and servings mismatches are rejected. Automatic alternatives need exact normalized names and matching known pack evidence. Unknown stock stays distinct from zero; out-of-stock rows and insufficient known stock are excluded from feasible allocations.

## Objective and limits

Meal coverage, servings, spend-band fit, and diversity remain the meal planner's first requirements. Among comparable meal candidates, effective cost is amount charged minus cash cashback. Points and miles have no invented monetary valuation; ranked noncash rewards and fewer merchants break effective-cost ties. Amount charged, before cashback, is used for spend bounds. Connected tender selection retains the shopper's configured benefit ranking.

Search uses a bounded beam with single-merchant seeds and merchant-offer threshold diversity. It preserves quantities, moves whole item lines between merchants, and reports search limits; it does not guarantee a global optimum or split units within a multi-quantity line. Insufficient comparable catalog products can leave a one-merchant basket as the best evaluated result.

Delivery follows this demo's existing rule: one basket-wide HK$30 fee below HK$400 goods subtotal. The optimizer supports Python quote hooks for other delivery rules, which must also be adopted consistently by checkout before using them in live plans. Merchant discounts use the configured Watsons/PARKnSHOP rules; illustrative A/B 5% rules are covered by synthetic tests, not added as real merchant promotions.

After changing backend code, restart your agent process on 8002 to load the tool. No frontend restart or ngrok change is required.
