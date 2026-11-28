---
status: accepted
---

# Places follows the Nominatim usage policy when it queries the public server

Places sends every reverse lookup to the public Nominatim server at `nominatim.openstreetmap.org`. With Extended Attributes on, it also sends an OSM lookup request there. The OpenStreetMap Foundation runs that server for free, with no service guarantee. Its operators block clients that break the [Nominatim Usage Policy](https://operations.osmfoundation.org/policies/nominatim/), and blocks apply without notice. Every Places install shares one application identity. A block would therefore stop Updates for every user at once.

We decided that Places treats the policy and the operators' requests in issues as hard requirements. Requests must identify Places, stay under the rate limit, avoid repeating identical queries, and use only the endpoints the policy allows.

**Source of truth:** `OSMClient` in `custom_components/places/osm_client.py`, which builds the URLs and the User-Agent and applies the throttle and the cache. The `OSM_*` constants are in `custom_components/places/const.py`, and the shared cache and throttle state are set up in `custom_components/places/__init__.py`. Read the values there. This ADR doesn't copy them.

## What Nominatim requires

The policy uses no RFC keywords. "Required" below means the policy or an operator states it as a rule, and "recommended" means they state it as advice.

| Requirement | Strength | Source and wording |
| --- | --- | --- |
| At most 1 request per second | Required | Policy: "No heavy uses (an absolute maximum of 1 request per second)." |
| The limit applies per application | Required | Policy: "the usage limits above apply per website/application: the sum of traffic by all your users should not exceed the limits." Places reads "application" as one installed copy of Places (see decision 3). |
| An identifying User-Agent or Referer | Required | Policy: "Provide a valid HTTP Referer or User-Agent identifying the application (stock User-Agents as set by http libraries will not do)." |
| Cache results and do not repeat identical queries | Required | Policy: "Results must be cached on your side. Clients sending repeatedly the same query may be classified as faulty and blocked." |
| Display attribution | Required | Policy: "Clearly display attribution as suitable for your medium." The data is ODbL licensed. |
| No `/details` endpoint for automated use | Required | lonvia (Nominatim maintainer) in custom-components/places#246 said Places' use of `/details` "is not permitted as per usage policy". |
| No systematic or grid queries, and no client-side autocomplete | Required | The policy lists both as forbidden uses that "will get you banned". |
| No personal data | Required | Policy: "Please do not submit personal data or other confidential material to any of our services." |
| Apps must be able to switch servers without a software update | Required | Policy: "Apps must make sure that they can switch the service at our request at any time (in particular, switching should be possible without requiring a software update)." |
| Avoid periodic requests | Strongly discouraged | Policy: "periodic requests from apps are considered bulk geocoding and as such are strongly discouraged. It may be okay if your app has very few users and applies appropriate caching of results." |
| Send an `email` parameter | Recommended | Reverse and Lookup API docs: "If you are making large numbers of request please include an appropriate email address to identify your requests." |
| Run your own Nominatim for heavy use | Recommended | Policy, and lonvia in custom-components/places#334 and osm-search/Nominatim#3877. |

### What the operators have said in issues

- **Identification lowers the block risk.** In osm-search/Nominatim#906 (2018), the operators said the servers automatically return HTTP 429 to IP addresses that send many requests, for a few hours. They also said: "If you make sure your queries include one of the following three items, 429 blocks are less likely: a) valid HTTP referrer, b) email parameter, c) non-stock HTTP user agent."
- **The User-Agent must name the app.** In osm-search/Nominatim#284 (2015), lonvia said "a general user agent like 'Dalvik' or 'OSMBonusPack' is not sufficient either". The policy requires an app to identify itself clearly in the User-Agent. In openstreetmap/operations#1069 (2024), the operators listed `python-requests/x.y.z` and placeholder names such as `YourAppName` among the top abusive User-Agents.
- **Do not get around blocks.** In odoo/odoo#134197 (2023), lonvia said of randomized User-Agents: "we do not look kindly on users trying to actively circumvent our measures". In the same thread, pnorman repeated that the limit applies to the sum of an application's traffic.
- **`email` can stand in when the headers cannot be controlled.** In osm-search/Nominatim#3790 (2025), mtmail said: "I think email address parameter can be used as alternative if one doesn't have control of referer, user-agent."
- **Blocks lift on their own.** In osm-search/Nominatim#3877 (2025), the operators said: "Blocking and unblock is automatic. Please wait 24 hours."

## Decisions

### 1. A Places-specific User-Agent with the version

Every request sends a User-Agent that names `places`, its version (`VERSION` in `const.py`), the Home Assistant version and the project URL. Nominatim can then tell Places traffic apart from other Home Assistant or aiohttp traffic, link a problem to a release, and find the maintainer. Places never sends aiohttp's stock User-Agent, and it never randomizes or rotates the header.

Why: custom-components/places#168 (2023) reported connection errors and linked the policy's User-Agent rule. Commit `0b9b935` ("Add user-agent to http requests", v2.4) added the header. The Home Assistant version and the project URL were added later.

### 2. The user's email address is sent as the `email` parameter

The optional `Email Address` setting (`CONF_API_KEY`, labelled "Email to use as OpenStreetMap API Key") is sent as the `email` parameter on reverse and OSM lookup requests. It identifies the install, so the operators can contact one user instead of blocking all Places traffic. It also makes 429 blocks less likely (Nominatim#906). The README's Notes section repeats Nominatim's request and points out that Nominatim keeps the address confidential and uses it only to contact them about a problem. The setting stays optional because Nominatim recommends it but does not require it.

### 3. One throttle per Home Assistant instance, at 1 request per second

All Places entries in one Home Assistant instance share a lock and a last-request time (`OSM_THROTTLE`). Each request waits until `OSM_THROTTLE_INTERVAL_SECONDS` (1 s) has passed since the previous one. Several tracked entities moving at once therefore queue up instead of bursting.

We interpret the policy's per-application limit as applying to each installed application, so each Home Assistant instance running Places has its own limit of 1 request per second. The limit does not cover all installations of the integration combined. The policy's "the sum of traffic by all your users should not exceed the limits" fits a hosted website or service, where one operator controls the access of every user of the page. Places has no such central point. Each install runs in the user's own Home Assistant and sends its own requests. This throttle enforces that limit, and the cache and the movement check keep each install well below it.

### 4. A shared cache of responses

Successful responses are stored in a shared in-memory `TTLCache` keyed by the full request URL. The cache holds `OSM_CACHE_MAX_SIZE` entries, and each entry expires after `OSM_CACHE_MAX_AGE_HOURS`. A repeat of the same query within that time is answered from the cache and does not reach Nominatim. Error responses and payloads with `error_message` are not cached. The cache is cleared when Home Assistant restarts. The Force Update button skips cache reads for one Update. It is triggered by the user, so the policy allows it.

Why: lonvia opened custom-components/places#334 (2025): "you are by now the most prominent user and way beyond what is acceptable by the usage policy... there is a lot of repetition in the requests. Please add some caching". PR custom-components/places#339 (commit `38c66c8`, v2.9.0) added the throttle and the cache together. The maintainer described the cache in #334 as "up to 500 queries" that "expire after 4 hours".

### 5. Reverse lookups only after real movement

A tracker state change or the scan interval starts an Update. Places does not query Nominatim on a timer. An Update makes a reverse lookup only when the coordinates differ from the last accepted Place by more than the movement threshold, which is 10 m or the reported GPS accuracy (see [ADR 0001](0001-gps-accuracy-zero-means-not-reported.md)). Identical coordinates never send a request. Scan-interval Updates run at most every `THROTTLE_INTERVAL` (10 minutes) per entry. This keeps Places away from the periodic, bulk traffic the policy discourages.

### 6. `/lookup` instead of `/details`

The Extended Attributes lookup uses `/lookup?osm_ids=...`. It is off by default, because it adds a second Nominatim request (and a Wikidata request) to each Update.

Why: in custom-components/places#246 (2023), lonvia said the `/details` endpoint is not permitted for automated use. The maintainer moved Places to `/lookup`.

### 7. Failed requests are not retried

A non-2xx response, a timeout or a JSON error is logged and the Update fails. Places does not retry inside the request. The next Update tries again, either on the next tracker state change that passes the movement check or on the next scan interval.

### 8. Attribution comes from the response

Places shows the response's `licence` string as the entity's `attribution` attribute (`OSMParser.set_attribution` in `parse_osm.py`).

## Consequences

- When you change the User-Agent, keep it identifying Places and its version. Never make it a stock library string, a placeholder, or a value that changes between requests.
- Do not remove or shorten the throttle or the cache, and do not add retry loops, without checking the policy again. The throttle is what keeps each install within its limit.
- A new Nominatim endpoint or a new automatic request needs checking against the policy first. `/details` is the precedent for an endpoint the operators asked Places to stop using.
- The cache key is the full URL, so any change in coordinates or language is a cache miss. The cache prevents identical repeats. It does not reduce lookups for an entity that keeps moving.

## Open questions

- **Mozilla prefix.** The User-Agent starts with `Mozilla/5.0`, a browser-style token, from commit `0b9b935`. The policy does not mention it and no operator has commented on it. Dropping it would make the header identify only Places.
- **Hard-coded server.** `nominatim.openstreetmap.org` is hard-coded in `OSMClient`. The policy requires that an app can switch servers at the operators' request without a software update. A configurable base URL would also let users run their own Nominatim, which the operators recommend for heavy use.
- **Empty `email` parameter.** When no email is set, Places sends `email=` with an empty value instead of leaving the parameter out.
