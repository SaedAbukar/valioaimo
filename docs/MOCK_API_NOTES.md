# Valio Aimo mock API — notes

Base URL: `https://junction26.valioaimo.fi` (set as `AIMO_BASE_URL` in `.env`).
Auth: header `X-API-Key: <key>` on everything under `/api` (`AIMO_API_KEY` in `.env`, never committed).
Source: the organisers' OpenAPI 3.1 file (copy in `data_raw/aimo_openapi.json`) and the challenge page.

> **Status (14 Nov 2026, 09:55):** live. Key in `.env`, `/api/ping` → 200, `/health`
> shows `liveApi.reachable: true`. The new-kitchen scenario orders on live prices and
> availability with 2 API calls (one price, one availability batch).
>
> **Gotcha:** the API is behind Cloudflare and returns **403 to Python's default
> `Python-urllib` User-Agent** (curl works). The client always sends `aimo-agent-gateway/0.2`.

## Endpoints

| Method | Path | Body | Notes |
|---|---|---|---|
| GET | `/api/ping` | – | Health check. `/health` in the gateway calls it. |
| POST | `/api/price` | `{customer, requestedDate, products[1..1000]}` | Price per **sales unit** for the requested delivery date. |
| POST | `/api/availability` | `{customer, requestedDate, products[1..1000]}` | Whether and when it can be delivered, and how much. |
| GET | `/api/products/download` | – | Redirect to the product data JSON (static; download once). |
| GET | `/api/delivery-reliability/download` | – | CSV `productId,deliveryReliability` (0–1). |
| GET | `/api/carbon-footprint/download` | – | CSV `productId,AVG kg CO2-eq/kg` (group average). |

`customer` does not change results in the challenge. More than 1,000 products → `422`. Rate limits exist but are not disclosed.

### Price response (per product)

| Field | Meaning | How the gateway uses it |
|---|---|---|
| `catalogPrice.value` / `valueWithTax` | Price per sales unit, without / with tax | `salesUnitPrice`; divided by the content per sales unit to get price per kg / L |
| `comparisonPrice`, `comparisonUnit` | Price per KG or L | Shown as "price per kg / L" when present |
| `tax.taxRate` | Official VAT % | Source of truth over `synkkaData.vatCode` |
| `listPrice`, `netPriceFound` | Before customer price; whether a net price exists | Kept in the offer for audit |
| `validFrom`, `validTo` | Price validity | The signed offer never outlives it (gateway lock is 15 min) |
| `error` | No price found | Product is not offered |

### Availability response (per product)

| Field | Meaning | How the gateway uses it |
|---|---|---|
| `salesBlock` | Cannot be ordered now | Treated as 0 available |
| `logisticModel` | `Stock` (we know quantities) or `Terminal` (supplier warehouse) | Terminal → `availableAmount` is always 999999, so reliability CSV matters more |
| `scheduleLines[0].availableAmount` | Quantity in sales units; 0 = not available | Multiplied by content per sales unit for planning |
| `scheduleLines[0].availableDate` | Earliest date that amount is available (may differ from the requested date) | Becomes the delivery date; later than need-by → "arrives too late" rule |
| `closingTime` | Order cut-off for that date | Shown in the Why? of the delivery card (todo) |
| empty `scheduleLines` | Cannot be delivered on any date | Excluded with a reason |

## Units

Unit codes (`KI`, `ST`, `PAK`, `KG`, `RAS`, `PRK`, `BOT`, `BAG`, `CS`, …) are technical
and not translated in the data. The gateway never shows them. It works in kg, L or
pieces: content per sales unit is read from the name (`1 l`, `2,5 dl`, `12 x …`) or
from `unitConversions[BASE_UNIT_OR_EACH].netWeight` × `units[].sizeInBaseUnits`.
`allowedLotSize` is the order step in sales units.

## How the gateway calls it

- Only for products already narrowed down by the playbook (the gaps after Recall,
  at most 6 candidates per gap), never "all products", as the API description asks.
- Batches up to 1,000 ids per call and caches each answer for 5 minutes.
- Any failure (no key, timeout, 4xx/5xx) falls back to demo values so the chat never breaks;
  `/health` shows `liveApi.reachable` and the last error.
- Code: [`gateway/adapter.py`](../gateway/adapter.py) (`AimoApiClient`), used by
  [`gateway/playbook/discover.py`](../gateway/playbook/discover.py) (`bridge`).

## Static data (downloaded files)

| File | Rows | Used for |
|---|---|---|
| Product data JSON (87 MB) | 17,546 products | Search index `gateway/data/aimo_products.json` (6.7 MB): names fi/en/sv, brand, vendor, category, temperature, units, allergens (GS1 codes → EU-14: CONTAINS / MAY_CONTAIN), diet claims, substitutions |
| Delivery reliability CSV | 4,425 | "always delivered in full" hint; delivery weight in ranking |
| Carbon footprint CSV | 11,033 | kg CO2e per kg (product-group average) |

Allergen codes seen: `AM` milk, `AW`/`UW`/`GB`/`GO`/`NR` gluten cereals, `AE` eggs, `AN` + `SA/SC/SH/SM/SP/SR/ST/SW` tree nuts,
`AP` peanuts, `AS` sesame, `AY` soy, `AF` fish, `AC` crustaceans, `UM` molluscs, `BC` celery, `BM` mustard, `AU` sulphites, `NL` lupin.
`ML` (likely lactose) and `X99` are not mapped. 189 products carry substitution rules.

## Observed behaviour (14 Nov 2026, sample of 200 random food products + spot checks)

**Price**
- All 200 had a price (`error: false`); an unknown code returns `error: true` with nulls.
- `comparisonUnit`: KG 148, L 27, none 25. **`catalogPrice / comparisonPrice` = content per sales unit**
  (e.g. 464119 milk 12-pack: €13.32 / €1.33 per L = 10 L). The gateway uses this instead of guessing
  from the product name; without a comparison unit the product is priced per piece.
- `netPriceFound` true for only 5 of 200; `listPrice` is higher than `catalogPrice` when it is.
- Validity: typically `2026-09-01`…`2026-12-31` or open-ended (`9999-12-31`). Prices did not change
  between requested dates 16.11. and 20.12.
- Tax 13.5 % on food (matches `vatCode` MEDIUM).

**Availability**
- `logisticModel`: Stock 90, Terminal 78, none 32. Products with no model have **empty `scheduleLines`**
  (16 %): cannot be delivered → the gateway drops them from Discover.
- Terminal: `availableAmount` always 999999 (unknown). Stock: real numbers (2, 5, 34, 146 … sales units)
  in 72 cases, `9999999999` in 18, `0` with **no `availableDate`** in 4.
- `availableDate` is the **earliest** delivery date and ignores the requested date: on Sat 14.11. every
  product said Mon 16.11. whether we asked for 15.11., 18.11. or 30.11. So "available by need-by" =
  `availableDate <= needBy`.
- `scheduleLines[].salesUnit` matched the product file's `salesUnit` in 167 of 168 lines.
- `closingTime` is the order cut-off for that earliest date (17:00 the day before for many Stock
  products; some show past dates such as 12.11., likely stale cut-offs on Terminal products).
- `timeNow` is real Helsinki time (14.11.); the gateway's demo clock stays at Fri 13.11. for the
  repeatable scenarios, so live products are one day "ahead".

**How the gateway maps it** (`discover.bridge`)
- unit and pack content from the comparison price; price per kg/L = `comparisonPrice`.
- amount ≥ 999999 → treated as ample (capped at 100,000 sales units); 0, missing date, sales block or
  empty schedule → not deliverable; otherwise amount × content.
- earliest delivery = `availableDate`; `logisticModel` and `closingTime` kept on the product.

No rate-limit responses seen (about 15 calls). Not yet tried: concurrent bursts, `Retry-After`.
