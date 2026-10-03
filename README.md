# HackU-Time-GrocerPoC

Monorepo assembled from the diverged [HackU-Time-Grocer](https://github.com/ToneKode/HackU-Time-Grocer) branches. Each package below is the folder from the branch that owns it, checked in on `main`.

| Path | Source branch | Commit | Role |
| --- | --- | --- | --- |
| `frontend/` | `front` | `c53e8aa35ffb94b70ab20fc32d7468ef89c62575` | Vue 3 storefront (Person 3) |
| `infra/` | `cursor/infra-database-eb5e` | `eb5e7b639ba0efd8d10f06c2bf77bb303bbdad73` | Postgres schema, Redis keys, demo seed (Person 2) |
| `dev/` | `cursor/payment-rail-chooser-a78f` | `179caeb38e2b85b324ac191a61cadf94af18a566` | Per-merchant payment rail chooser |
| `agent-brain/` | `person-1/shopping-call` | `a77378a7cfdca068130a33c1a5fd915a84106fec` | Shopping agent on port 8002 (Person 1) |
| `backend-policy/` | `person-1/shopping-call` | `a77378a7cfdca068130a33c1a5fd915a84106fec` | Policy, audit ledger, and escalations on port 8001 (Person 2) |

`dev1` (`07a342517df161ae5f340f2afa138fd8d51e5663`) also contains `backend-policy/`. `person-1/shopping-call` is a descendant of that commit and is the tree checked in here. The only product change is an empty `CATEGORY_BLACKLIST`, so Food, Alcohol, Electronics, and Health are allowed. That matches `agent-brain/backend/policy_rules.py`.

Root `.env.example` is the infra branch copy, which adds the Postgres and Redis variables. Copy it to `.env` before `docker compose` in `infra/`.

Each package README has its own run steps.
