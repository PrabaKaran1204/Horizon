# Horizon ERP - Inventory Sync API

REST endpoint that external systems (planning tools, the Delhi DC WMS, BI) call to pull the
current stock position of a warehouse, including low-stock alerts derived from `Item Reorder`.

| | |
| --- | --- |
| Method | `POST` (also `GET` for quick demos) |
| URL | `/api/method/horizon_erp.api.inventory.get_inventory_snapshot` |
| Short alias | `/api/method/horizon_erp.api.get_inventory_snapshot` (re-export in `horizon_erp/api/__init__.py`) |
| Brief alias | `/api/method/get_inventory_snapshot` - requires the `override_whitelisted_methods` line below in `hooks.py` |
| Auth | `Authorization: token <api_key>:<api_secret>` (Frappe token auth) or a logged-in session |
| Permission | caller needs **read** on `Bin` (Stock User / Stock Manager / Sales User / Purchase User ...) |
| Rate limit | 100 requests per hour per API client (see below) |
| Logging | every call -> `Inventory API Log` (Horizon Integration) |

Code: `horizon_erp/api/inventory.py`, `horizon_erp/api/rate_limit.py`,
`horizon_erp/horizon_integration/doctype/inventory_api_log/inventory_api_log.py`.

To enable the brief's bare URL, the lead adds this to `horizon_erp/hooks.py`:

```python
override_whitelisted_methods = {
	"get_inventory_snapshot": "horizon_erp.api.inventory.get_inventory_snapshot",
}
```

## 1. Authentication setup (API key / secret)

Standard Frappe token auth; the API client is identified by the **user who owns the key**.

1. Create a dedicated integration user (for example `wms-sync@horizon.example`) and give it a role
   with read access to `Bin` (`Stock User` is enough; add `Warehouse Manager` if it must also see
   the log). Do not use Administrator in production.
2. User form > Settings > **API Access** > *Generate Keys*. Copy the secret - it is shown once.
   Equivalent on the bench:

   ```bash
   bench --site horizon.local execute frappe.core.doctype.user.user.generate_keys \
       --kwargs '{"user": "wms-sync@horizon.example"}'
   # -> {"api_key": "...", "api_secret": "..."}
   ```

3. Send `Authorization: token <api_key>:<api_secret>` on each request. The session user becomes the
   key owner, which is what the rate limiter and the log use as `client`.

Optional site config (`sites/horizon.local/site_config.json`):

```json
{"horizon_api_rate_limit": 100}
```

## 2. Request

```json
{"warehouse": "Delhi DC", "filter_by_criticality": true}
```

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `warehouse` | string | yes | Resolved leniently, in this order: exact Warehouse ID (`Delhi DC - HML`), then `<value> - <company abbr>` for every company, then `warehouse_name` match. Ties prefer the default company. A **group** warehouse is aggregated over all its enabled leaf warehouses (`lft`/`rgt`). |
| `filter_by_criticality` | bool | no | `true`, `"true"`, `"1"`, `1` are truthy. When set, only items with `Item.criticality` in **A, B** are returned. |
| `_simulate_failure` | any | no | Undocumented test hook. Only honoured when `developer_mode` is on; forces the 503 path. |

`GET` works too: `?warehouse=Delhi%20DC&filter_by_criticality=1`.

Only `is_stock_item = 1`, `disabled = 0` items that have a `Bin` row in the selected warehouses are
returned. Data comes from one aggregate query (`Bin` x `Item`) plus one query for `Item Reorder`;
no per-item loops.

## 3. Successful response (HTTP 200)

Frappe wraps the return value of a whitelisted method in `message`:

```json
{
  "message": {
    "timestamp": "2026-10-16T10:30:00+05:30",
    "warehouse": "Delhi DC - HML",
    "warehouses_included": ["DEL Finished Goods - HML", "DEL Raw Materials - HML"],
    "generated_in_ms": 42.3,
    "items": [
      {
        "item_code": "SP-IMPELLER",
        "item_name": "Impeller 200mm",
        "item_group": "Spares",
        "criticality": "B",
        "available_qty": 10.0,
        "actual_qty": 15.0,
        "reserved_qty": 5.0,
        "projected_qty": 12.0,
        "reorder_point": 8.0,
        "reorder_qty": 50.0,
        "below_reorder": false,
        "valuation_rate": 3200.0
      }
    ],
    "low_stock_alerts": [
      {"item_code": "SP-SEAL", "available_qty": 2.0, "reorder_point": 8.0, "shortfall": 6.0, "criticality": "A"}
    ],
    "summary": {"item_count": 37, "low_stock_count": 1, "total_stock_value": 1254300.0}
  }
}
```

Field semantics:

| Field | Source / formula |
| --- | --- |
| `timestamp` | server time in the site timezone, ISO-8601 with offset |
| `warehouse` | resolved Warehouse ID |
| `warehouses_included` | leaf warehouses that were aggregated (the warehouse itself when it is a leaf) |
| `actual_qty`, `reserved_qty`, `projected_qty` | `SUM` over `tabBin` for the included warehouses |
| `available_qty` | `actual_qty - reserved_qty` |
| `reorder_point`, `reorder_qty` | `Item Reorder` row for one of the included warehouses; else any reorder row of the item; else `0` |
| `below_reorder` | `reorder_point > 0 and available_qty < reorder_point` |
| `valuation_rate` | `SUM(stock_value) / SUM(actual_qty)` (weighted), falls back to `MAX(Bin.valuation_rate)` |
| `low_stock_alerts` | items with `below_reorder = true`; `shortfall = reorder_point - available_qty` |
| `summary.total_stock_value` | `SUM(Bin.stock_value)` of the returned items |

Quantities are rounded to 3 decimals, amounts to 2. Response headers on every call:
`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` (seconds until the window resets).

## 4. Error responses

All application errors return a JSON body (wrapped in `message`) with the HTTP status set:

| HTTP | `error` | When | Body |
| --- | --- | --- | --- |
| 400 | `missing_warehouse` | `warehouse` missing/blank | `{"error": "missing_warehouse", "message": "Parameter 'warehouse' is required", "timestamp": "..."}` |
| 404 | `invalid_warehouse` | no Warehouse matches | `{"error": "invalid_warehouse", "message": "Warehouse 'X' not found", "hint": "Pass the Warehouse ID (e.g. 'Delhi DC - HML') or its Warehouse Name (e.g. 'Delhi DC')", "timestamp": "..."}` |
| 429 | `rate_limited` | hourly quota exceeded | `{"error": "rate_limited", "message": "Rate limit of 100 requests per 3600 seconds exceeded for client ...", "retry_after_seconds": 1834, "limit": 100, "remaining": 0, "reset_seconds": 1834, "window_seconds": 3600, "timestamp": "..."}` + `Retry-After` header |
| 503 | `temporary_failure` | the stock query raised (DB down, lock timeout ...) | `{"error": "temporary_failure", "message": "Inventory data is temporarily unavailable, please retry", "retry_after_seconds": 30, "timestamp": "..."}` |

Framework-level failures use Frappe's standard exception body (`{"exception": "...", "exc_type": "..."}`), not the shape above:

| HTTP | `exc_type` | When |
| --- | --- | --- |
| 401 | `AuthenticationError` | bad / missing token |
| 403 | `PermissionError` | anonymous (Guest) call, or the key owner has no read permission on `Bin` |

Clients should retry 429 and 5xx; never retry other 4xx.

## 5. Rate limiting

* **100 requests per hour per API client**, where client = the authenticated user (owner of the
  API key); IP address is used only for the Guest fallback (which is rejected anyway).
* Implemented in `horizon_erp/api/rate_limit.py` (`@rate_limited`) with Redis `INCR` + `EXPIRE` on
  `horizon:ratelimit:<client>:<bucket>`, `bucket = epoch // 3600`. This is a fixed one-hour window
  (an approximation of "rolling hour"): the counter resets at the top of each UTC hour; `Retry-After`
  / `X-RateLimit-Reset` tell the client exactly how long to wait.
* Limit is configurable without code changes: `horizon_api_rate_limit` in `site_config.json`.
* Rejected calls are logged with status **Rate Limited** and are not counted towards the window
  twice (one INCR per request, so hammering while blocked does not extend the block).
* Why not Frappe's built-ins: `frappe.rate_limiter.rate_limit` keys by IP / a form field, answers
  HTTP 417 with no `Retry-After`, and offers no hook to log the rejected call; the site-wide
  `frappe.conf.rate_limit` is one global CPU-time budget for the whole site, not per client. Our
  decorator exposes a duck-typed `frappe.local.rate_limiter` so `frappe.app.process_response`
  appends the standard `X-RateLimit-*` / `Retry-After` headers; the same values are in the 429 body
  for clients that cannot read headers.

Reset a client's counter (ops):

```bash
bench --site horizon.local execute horizon_erp.api.rate_limit.reset_rate_limit --args '["wms-sync@horizon.example"]'
```

## 6. Logging and the API Usage Report

Every call writes one `Inventory API Log` row: `timestamp`, `endpoint`, `client`, `parameters`
(JSON), `response_time_ms`, `http_status`, `status` (Success / Invalid Input / Rate Limited /
Error), `error` (traceback, truncated to 5000 chars) and `ip_address`. Logging is wrapped in
`try/except` and can never break the API response. Errors are also written to **Error Log**.

Frappe rolls the transaction back when a request ends in an exception, and rolls back `GET`
requests by default. The log helper therefore sets `frappe.local.flags.commit` (so GET calls persist)
and commits explicitly on the two paths that re-raise (401 / 403).

**API Usage Report** (Horizon Integration > Reports; roles System Manager, Finance Director):
filters From/To Date (default last 7 days), Client, Status; columns Client, Endpoint, Calls, Success,
Failed, Rate Limited, Avg Response ms, P95 Response ms (nearest-rank, computed in Python), Last
Call; line chart of calls per day with average response time; summary cards with totals.

## 7. curl examples

Replace `KEY:SECRET`. On a bench where port 8000 serves the default site (`serve_default_site`),
run a dedicated server for this site: `bench --site horizon.local serve --port 8001`.

```bash
BASE=http://horizon.local:8000
AUTH='Authorization: token KEY:SECRET'

# success (POST)
curl -s -X POST $BASE/api/method/horizon_erp.api.inventory.get_inventory_snapshot \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"warehouse":"HQ Raw Materials","filter_by_criticality":true}'

# -> HTTP/1.1 200 OK
#    X-RateLimit-Limit: 100  X-RateLimit-Remaining: 99  X-RateLimit-Reset: 2978
#    {"message":{"timestamp":"2026-10-16T13:43:16+05:30","warehouse":"HQ Raw Materials - HML",
#      "warehouses_included":["HQ Raw Materials - HML"],"generated_in_ms":17.5,
#      "items":[{"item_code":"CMP-BEARING-6205","item_name":"Ball Bearing 6205","item_group":"Components",
#                "criticality":"B","available_qty":200.0,"actual_qty":200.0,"reserved_qty":0.0,"projected_qty":200.0,
#                "reorder_point":100.0,"reorder_qty":200.0,"below_reorder":false,"valuation_rate":250.0}, ...],
#      "low_stock_alerts":[],"summary":{"item_count":11,"low_stock_count":0,"total_stock_value":598000.0}}}

# short alias, GET
curl -s -G $BASE/api/method/horizon_erp.api.get_inventory_snapshot -H "$AUTH" \
  --data-urlencode "warehouse=Delhi DC" --data-urlencode "filter_by_criticality=1"

# unknown warehouse -> 404
curl -s -i -X POST $BASE/api/method/horizon_erp.api.inventory.get_inventory_snapshot \
  -H "$AUTH" -H "Content-Type: application/json" -d '{"warehouse":"Nowhere DC"}'
# -> HTTP/1.1 404 NOT FOUND
#    {"message":{"error":"invalid_warehouse","message":"Warehouse 'Nowhere DC' not found",
#      "timestamp":"2026-10-16T13:40:21+05:30","hint":"Pass the Warehouse ID (e.g. 'Delhi DC - HML') or its Warehouse Name (e.g. 'Delhi DC')"}}

# missing warehouse -> 400
curl -s -X POST $BASE/api/method/horizon_erp.api.inventory.get_inventory_snapshot \
  -H "$AUTH" -H "Content-Type: application/json" -d '{}'
# -> {"message":{"error":"missing_warehouse","message":"Parameter 'warehouse' is required","timestamp":"..."}}

# simulated backend failure (developer_mode only) -> 503
curl -s -X POST $BASE/api/method/horizon_erp.api.inventory.get_inventory_snapshot \
  -H "$AUTH" -H "Content-Type: application/json" -d '{"warehouse":"HQ Raw Materials","_simulate_failure":1}'
# -> {"message":{"error":"temporary_failure","message":"Inventory data is temporarily unavailable, please retry",
#      "timestamp":"...","retry_after_seconds":30}}

# rate limit demo: the 101st call within the hour
for i in $(seq 1 101); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST \
    $BASE/api/method/horizon_erp.api.inventory.get_inventory_snapshot \
    -H "$AUTH" -H "Content-Type: application/json" -d '{"warehouse":"HQ Raw Materials"}'
done | sort | uniq -c
# -> 100 200 / 1 429 ; the 429 carries:
#    HTTP/1.1 429 TOO MANY REQUESTS
#    X-RateLimit-Limit: 100  X-RateLimit-Remaining: 0  X-RateLimit-Reset: 2806  Retry-After: 2806
#    {"message":{"error":"rate_limited","message":"Rate limit of 100 requests per 3600 seconds exceeded for client Administrator",
#      "retry_after_seconds":2806,"timestamp":"2026-10-16T13:43:13+05:30","limit":100,"remaining":0,"reset_seconds":2806,"window_seconds":3600}}

# inspect the log
bench --site horizon.local execute frappe.get_all --kwargs \
  '{"doctype":"Inventory API Log","fields":["status","http_status","count(name) as calls"],"group_by":"status, http_status"}'
```

## 8. Sync client with retry

`horizon_erp/client/inventory_sync_client.py` is standalone (only `requests`; no frappe import).

```bash
pip install requests
python horizon_erp/client/inventory_sync_client.py --url http://horizon.local:8000 \
    --key KEY --secret SECRET --warehouse "Delhi DC" --criticality [--json] [--log-file inventory_sync.log]
```

Behaviour:

* `fetch_snapshot()` makes up to 4 attempts: 3 retries with fixed exponential backoff **1 s, 5 s, 25 s**
  on HTTP 429, any 5xx, and connection/timeout errors. The server's `Retry-After` is logged for
  information but the fixed schedule is honoured (spec). Other 4xx (400/401/403/404) raise
  `SnapshotError` immediately.
* Each attempt is logged with a timestamp to stdout and appended to `inventory_sync.log`.
* On success the summary and the low-stock alert table are printed; `--json` dumps the full snapshot.
* Library use: `fetch_snapshot(base_url, api_key, api_secret, warehouse, filter_by_criticality)`
  returns the `message` dict; `session` and `sleep` are injectable for tests.

## 9. Tests

```bash
bench --site horizon.local run-tests --app horizon_erp --module horizon_erp.api.test_inventory_api --skip-test-records
```

`horizon_erp/api/test_inventory_api.py` creates its own `APITEST-*` warehouses, items and Bin rows
(deleted again in `tearDownClass`) and covers: lenient warehouse resolution and group aggregation,
field math (`available_qty`, reorder fallback, `below_reorder`, valuation, summary), criticality
filter parsing, 400 / 404 / 503 bodies and log rows, 403 log row surviving a rollback, 429 after the
limit with headers and a *Rate Limited* log row, the 100/hour default, and the client's backoff
schedule with a fake session (no network).
