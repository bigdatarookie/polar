# Saved research from the ordinary strategy list

The default real-history workspace now discovers the same immutable research
catalog as Saved research. The main strategy section lists the actual records
in content-ID order, with exact IDs, question/phase labels, supplied date grid,
recorded position symbols, wealth/cost basis, supplied primary metrics and the
independent financial/evidence assessment. It does not calculate returns, train
models, create orders, publish records or alter independent verdicts.

Each catalog page has at most10 records. A separate instance of the existing
research client loads that page's details and commits a coherent page only after
all identities and existing wire validation pass. The price loader and saved
renderer keep their independent cancellation/state. Failed updates retain the
last complete page and expose Retry; an empty catalog is explicitly empty, with
no fallback. Pagination and refresh use the existing read-only GET routes.

An exact `openResult(contentID, pageOffset)` method on the existing research
workspace opens the selected record. It does not overload legacy `?run=` or
convert portfolio NAV into a single-ticker candle overlay. Price history return
retains its instrument/revision, range, cursor and measurement; the existing
hidden-chart resize path and research table endpoint focus fixes remain intact.
The main-list origin button is focused on return when still present. Saved
record/sample state follows the existing renderer, including distinct FINAL and
diagnostic VALIDATION records and their separate assessments.

Compatibility is based on actual metadata, never a ticker-only match. The list
explains different data revision/hash, source alias or portfolio, synthetic
adjusted reference-unit versus raw OHLC basis, currency and selected dates
outside the saved period. Lack of a content-bound instrument source relation is
explicit. A future direct attribution requires the exact history revision and
manifest hash, a `history_instrument` provenance relation bound to that
instrument/hash, a one-symbol portfolio with the exact source alias, matching
currency, PRICE_ONLY wealth basis and raw history basis. Even then NAV remains a
separate wealth series, not candles or an inferred order tape. Current saved
multiasset/synthetic comparisons remain available through their real results
while truthfully separate from the selected price history.

The original Saved research API/renderer acceptance remains scoped evidence.
Complete ordinary-entry acceptance belongs to the assigned independent v0.36
System2 owner: history/asset → MAIN strategy list → exact model/benchmark result,
phase/period/universe/cost/risk/limits/assessment → result and asset changes →
correct return, including empty/error/refresh and narrow interactions on the
accepted served candidate. Source/component/preview evidence alone is not that
final verdict. Existing C and private OBS work is independent and is not rerun
for this presentation change.
