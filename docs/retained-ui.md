# Retained research workspace

Open `/ui/` on the existing API origin. The packaged selected Polar workspace uses
only GET requests and local assets. It never registers a dataset, submits/cancels
a job or computes a new report. Original `UI Demo/` remains outside the package.
There is no fixture fallback or runtime CDN. Independent browser/runtime and
financial acceptance remain separate from packaging/component checks.

Use the Asset field for actual dataset versions/instruments, with Previous/Next
dataset-page buttons. The lower table lists actual retained runs for the selected
dataset; run pages and page-only sorting are explicit. A single dataset or run is
valid. Defaults/reset select the first record in the stable backend order, never
the best return. Each dataset/instrument pair is distinct. Record labels use the
actual strategy version, run identity and creation time.

Selection updates `?dataset=…&run=…`; reload and browser Back/Forward validate
those identities through the backend, including off-page records. A run-only URL
resolves its own dataset. An explicit URL takes precedence over stored selection.
Refresh reloads retained data without computation. A new versioned workspace key
ignores demo state and validates IDs/control values/window bounds. New selection
or refresh clears old charts while loading; request generations and cancellation
prevent an earlier response from replacing the current record. Errors, empty
catalog/pages and unavailable reports are distinct. Refresh retries outages.

The API/CLI's existing `/v1` operations remain unchanged. UI projections are shared
Service operations, with the following GET-only contract:

| Route | Result |
| --- | --- |
| `/v1/ui/datasets?limit=10&offset=0` | `{items,limit,offset}` of validated retained dataset projections |
| `/v1/ui/datasets/ID` | Direct retained dataset projection for URL navigation |
| `/v1/ui/datasets/ID/runs?limit=10&offset=0` | `{items,limit,offset}` with run metadata, availability/status and report-backed metric summaries |
| `/v1/ui/runs/UUID?dataset_id=ID` | `polar.ui-run/1` detail, optional expected-dataset check |

Lists require limit 1..10/nonnegative offset. Ordering remains dataset ID and
run creation time/ID. Next is available for full pages; an empty final page is
valid. Search/sort is explicitly local to the current page, not a global ranking.
Dataset projection contains canonical ID/hash, original source hash, registered
at, retained name/market/instrument/ticker metadata, supplied sessions/raw OHLC
statuses and quality inspection. It excludes features, full source bytes/body
and ingestion environments. Dataset integrity uses the existing Service binding.

Run detail contains allowlisted run metadata, dataset projection, report
availability, report fields and evidence hashes. Non-complete jobs have no report
or invented portfolio values. Completed `NO_DATA`/`INVALID` remain explicit report
statuses, not financial success. Completed detail verifies DB-bound manifest,
all artifact hashes, report/config/dataset/run/attempt correspondence, and report
identity. The accepted engine's genuine `INVALID` shape omits success-only
`config_hash`/`strategy_version`; those missing fields are never fabricated.
For INVALID reports, hash-verified `inputs.json` must contain a valid Dataset
matching registered canonical identity and a valid RunConfig matching the entire
stored config (including provenance refs). Any supplied report identity fields
still must match; successful/NO_DATA reports keep their required-field checks.
Known stable engine diagnostic codes and the actual `metrics.performance`
invalid status/null are exposed; unknown diagnostic payloads are unavailable,
never echoed. Catalogs retain INVALID alongside healthy runs. This differs from
genuine `NO_DATA` (empty sessions), which retains its accepted success-shape
identity fields and null accounting metrics. The original calculation revision comes only from hash-verified retained
`environment.json`; missing/non-SHA revisions are `UNKNOWN`. Current API revision
is a separate reported field. No raw environment, credentials, file paths,
actor/queue/team internals or mutable acceptance flag is returned.

Missing records use existing 404 codes. Mismatch/malformed records return stable
409 `RUN_DATASET_MISMATCH`, `REPORT_IDENTITY_MISMATCH` or
`RETAINED_RECORD_INVALID`; dataset corruption retains `DATASET_INTEGRITY_ERROR`.
Hash/dependency failure uses existing sanitized 503 `DEPENDENCY_UNAVAILABLE`.
Invalid query bounds/UUID use sanitized 422. UI projection routes accept no POST.

Daily raw prices retain actual session timestamps and statuses. Missing/absent/
settlement-only rows are gaps; no OHLC is fabricated. Weekly/monthly buckets use
first open/max high/min low/last close only when every supplied session in that
bucket has observed OHLC; any gap makes that bucket unavailable. Coverage reports
observed/supplied sessions and does not claim a complete exchange calendar.
Intraday intervals are disabled with a daily-source reason. Range controls clamp
to the last actual observation without generating extra history. Volume and a
passive benchmark are unavailable; no zero volume bars or counterfactual benchmark
are generated. SMA20 is only a labeled display transform of 20 gap-free closes.

NAV aligns on the last actual supplied session in each bucket; missing NAV never
forward-fills. Price index uses the first usable actual raw open; NAV index uses
retained `initial_cash`, as separately labeled bases. Missing/invalid/zero bases
disable that index. Raw observed zero is still displayed as zero. Display-only
chart conversion/smoothing never changes stored values or raw measurements.
Raw strings/status/units remain available in readouts/popover. Measurements use
actual source timestamps and exact decimal subtraction, not line interpolation.
Supported source controls retain pin/move/edge flip/next-click clear, keyboard,
fixed-span wheel/slider, independent range/interval and compatible theme behavior.
Unavailable points never become a measurement. Narrow Tools retains focus handling.

Table/popover return, Sharpe, drawdown and fees come from retained report metrics,
including null/status/evidence_status/reason. Only percent conversion/display
rounding is applied; no new Sharpe/annualization or visible-window metric engine.
Ending NAV is the last retained observation; the popover separately labels
`last NAV − initial cash`. Actual signed fills include their original execution,
receipt and decision-session context. Instructions and their reasons/times remain
separate; fill-row references are presentation references, not invented service
fill IDs or entry/exit round trips. No per-trade P&L or closed-trade count is inferred.

`docs/ui-asset-lineage.json` binds all 22 selected runtime/license files to the
intake source and adapted hashes. Five entrypoints are adapted; 17 assets/notices
remain exact copies, including fonts, ECharts, bear credits and historical license
closure. Entry-point diffs are retained with slice evidence, not loaded at runtime.
The selected light/dark layout, typography, purple/bear and plot/Tools interaction
are the design reference. No replacement design/framework was introduced.

Controlled checks: `pytest tests/test_ui_projection.py`, and
`node --test tests/ui_components.cjs`. The latter uses Node/DOM geometry doubles,
not a real browser. Independent QA must check actual assembled `/ui/`, retained
record/value identity and desktop/390px interactions. Source checks do not prove
actual image contents, browser rendering, PostgreSQL or financial performance.
Assembly must be separately authorized on the existing task contour after
conflicting state custody ends, pinning candidate/image/assets/schema/config,
retained IDs/hashes/counts and CPU/RAM/disk/browser allowances. No new job,
migration, full second stack or automatic worker upgrade is needed.
