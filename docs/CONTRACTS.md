# Data and API contracts — version 1.0

## Snapshot envelope

The executable contract is `engine.validate`; `data/demo.json` is a complete example. Unknown fields are rejected so incorrect assumptions cannot be silently ignored. JSON numeric strings and booleans are not accepted as quantities. Each SKU has exactly 28 unique daily demand rows immediately before `as_of`. ISO dates must be `YYYY-MM-DD`. All unit quantities are integers at ingestion. Internal mean-demand projections may be fractional.

| Object | Required fields | Semantics |
|---|---|---|
| Envelope | `schema_version`, `as_of`, `warehouse`, `currency`, `budget_idr`, `review_days`, `safety_days`, `products`, `lots`, `demand`, `offers`, `inbound` | Version `1.0`; one warehouse snapshot at start of `as_of`; currency `IDR`; integer budget ≥0; review 1–28 days; safety 0–14 days |
| Product | `sku`, `name`, `unit`, `storage`, `priority`, `min_remaining_days`, `max_stock_units` | Unique SKU; base unit string; storage ambient/cold (cold is blocked by planner); priority 1 highest to 5 lowest, assigned by business owner; remaining-life policy 1–730 days; conservative per-SKU physical storage cap |
| Lot | `lot_id`, `sku`, `quantity`, `reserved`, `expiry`, `status` | Globally unique lot row ID in snapshot; quantity is total physical stock, reserved is a subset ≤quantity; released/quarantine/recalled; expiry is an exclusive boundary after remaining-life adjustment. Expired stock remains in physical-cap calculation until removed by an updated source snapshot |
| Demand | `date`, `sku`, `units`, `stockout` | Unique SKU/date; historical demand in the SKU base unit, not money; units ≥0; zero requires an explicit row; any stockout flag blocks mean forecasting for the SKU |
| Offer | `offer_id`, `sku`, `supplier`, `approved`, `lead_days`, `pack_size`, `moq`, `unit_cost_idr`, `capacity_units`, `shelf_life_days`, `valid_until` | Unique offer ID; approved is authoritative master-data eligibility, not an LLM extraction; lead 1–60 days; pack/MOQ positive; unit cost positive integer IDR; capacity for this order; shelf life is guaranteed days **from receipt**, 1–730; validity inclusive of as_of |
| Inbound | `po_line_id`, `sku`, `quantity`, `arrival`, `expiry`, `status` | Unique outstanding PO-line ID; quantity means remaining open units, not original order total; confirmed/unconfirmed; only confirmed receipts counted; overdue confirmed ETA is an import error; expiry must be after arrival |

Money excludes freight/tax unless already included in unit cost; mixed currencies and separate landed-cost components are unsupported. No UOM conversion is attempted. `box` must mean the same thing in demand, stock and offers for that SKU. The upstream adapter must net returns and map orders/sales consistently. For this baseline, reserved stock is unavailable and the forecast represents future unreserved demand. Do not subtract reservations and also forecast the same committed orders.

Snapshot arrays are capped at 10,000 rows each, products at 100; HTTP payload capped at 2 MB. Current one-file atomic validation rejects the entire import on malformed records. Unsupported analytical conditions (cold products/censored history) instead produce a blocked SKU, allowing other SKU recommendations to be reviewed.

## Decision output

`engine_version`, `snapshot_hash` (SHA-256 of canonical JSON), `as_of`, `warehouse`, currency, method, budget/spend/remaining budget and SKU `lines`. Line status is `RECOMMEND`, `NO_ORDER` or `BLOCKED`. Eligible lines include forecast mean, usable stock, baseline daily trace, common horizon, supplier options, feasibility reasons and the selected option. Each projection reports unmet units, end stock, shelf-life excluded units, first-shortage date and daily trace. “Excluded” means stock no longer meets this modeled shelf-life policy; it is not necessarily physically expired or a booked financial write-off.

Source traceability is by stored complete snapshot, stable SKU/lot/offer/PO IDs and engine version. This slice does not expose full snapshot download in the UI; it is retained in SQLite for replay. The UI audit panel shows source hash and decision events.

## Local API

| Route | Behavior |
|---|---|
| `GET /api/session` | Returns a local session token; not user authentication |
| `GET /api/demo` | Generates synthetic example dated to the host's current local date |
| `GET /api/runs` | Last 20 run IDs/statuses/timestamps |
| `GET /api/runs/{id}` | Stored result, current/superseded state and audit events |
| `POST /api/plan` | Validates body as snapshot, computes plan and stores a PENDING run; 201 |
| `POST /api/decision` | `{run_id, action, actor, reason, snapshot_hash}`; action APPROVED/REJECTED; current snapshot and state checked on backend |
| `POST /api/export` | `{run_id}`; returns stable `DRAFT_NOT_SENT` requisition for an approved current run; no external side effect |

All POST requests require `Content-Type: application/json` and `X-Nexus-Token` from this server session. Host allowlist is loopback, responses are not CORS-enabled and use a restrictive same-origin content policy. Validation errors return 400, token errors 403, state conflicts 409, unsupported content type 415, size errors 413. There is no endpoint accepting an arbitrary supplier payload or modifying an approved result.

## Pilot contract extensions (not implemented)

- Envelope: organization/warehouse IDs, source-system revision, ingestion timestamp/timezone, freshness SLA and decision-cycle ID.
- Products and inventory: canonical UOM conversion, product authorization/quality state, storage volume/temperature class, per-batch release evidence, committed-demand timeline, returns and disposal states.
- Supplier/PO: supplier authorization validity, price version and currency conversion approval, landed-cost components, delivery calendars and ETA distributions, acceptance/partial receipt/cancellation events.
- Forecast: SKU/location/origin/horizon, model and dataset version, point/quantile arrays, calibration and backtest metrics, warning/abstention reasons.
- Approval: authenticated subject and role, authority limit, immutable plan revision, override diff/reason and budget reservation.
- Execution: approved requisition ID, ERP idempotency key, requested/sent/accepted/rejected/reconciled states and external receipt IDs.
