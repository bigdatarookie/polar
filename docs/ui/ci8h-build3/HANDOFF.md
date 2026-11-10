# Polar frontend refinement

Owned branch build3/ci8h-ui-20261109, isolated from accepted ad20035efdd972778c0b1f48f43bf51f935a48d1. Backend/common runner/serving remain PE/SRE owned.

## Chart stage

- Data details native disclosure retains exact raw values/statuses. Calculation/source details are on demand in the rail. At narrow widths data disclosure precedes the scrollable plot for immediate access.
- Volume toggle releases its pane height and intervening gap to candles; RSI/reference axes remain attached to the same timeline. Volume and disclosure preferences persist; Reset restores volume on/details closed.
- Overlay card samples and ECharts strokes share chart-ui.js definitions, including all three BB lines and both reference lines. No new assets or SVGs.

Author checks: node --test tests/ui_components.cjs tests/ui_chart_refinements.cjs (15 passed); app/chart-ui syntax; actual AAPL/1M/Light/all overlays at1440x900 and390x844. Exact baseline had7 pre-existing component-test failures: stale VM script dependencies and retained-mode/control/error expectations were repaired in the allowed harness. No production semantics were changed to satisfy them.

Preview http://127.0.0.1:18983/ui/ uses owned static frontend and GET-only upstream18081. SRE20:30 current upstream is accepted0cd2e1f/tree989d9c32, CID2fe3fd57. It is not the new research backend. Preview PID40861, born2026-11-09T20:30:01.822Z; no backend/source lifecycle action. Useful images are outside Git at state/build/ci8h-build3. Independent Stage1 QA1 PASS on a31038658b181db0c002275cc1c71e9cc10b32de, report state/orch/missions/ci-research-ui-8h/qa/qa1/coverage.md. This covers chart stage only; author checks are not independent acceptance.

## Public controls / reset

Default Stored history mode, first registered asset; reset uses actual catalog. Match baseline1440x900, Light(Settings), AAPL,1M, Overlays SMA20/EMA20/BB20k2/RSI14/reference. Wait for Context ready after each asynchronous request. Volume is a pressed button in legend. Data details summary toggles exact raw text; calculation disclosure follows each overlay's periods/sample. Chart focus + Enter pins/clears; arrows move selected point; Escape clears. Real history and retained test mode remain explicitly separate.

## Saved research

Wire-v1.1 authoritative source: state/platform/ci8h-research-ui-20261109/wire-v1.1/API-CONTRACT.md and sibling schemas. Contract is a field freeze; actual backend/data acceptance remains separate.

The new anchor is TYPE data visualization: supplied nominal USD NAV by named STRATEGY/BENCHMARK/CONTROL leg, complete UTC grid, no frontend economics. It uses the already pinned ECharts6.0.0 canvas renderer; no new pictorial SVG/assets. Original price workspace remains separate and retains its context.

research.js validates envelope/selection identities, grid/leg/ledger consistency and exact-bound reviews. It never replaces non-OK values or an empty catalog. Sharpe uses decimal-string HALF_EVEN display with full source tokens retained; renderer underflow remains a gap with a precision notice. Native sample slider exposes actual supplied per-point values/ledger, including initial NOT_APPLICABLE return. Research workspace exposes producer metrics/comparisons/criteria, costs exactly once, coded limitations, basis and exact-content assessments; producer statements are distinct from independent review.

Research registration followed QA1's Stage1 safe boundary. Topbar Price history/Saved research navigation preserves original price context; at390px the header adds30px. Refresh delegates to the active workspace; Reset returns to default price context and clears cached research. Hidden price plots skip rendering until visible, with actual pinned source/range/values retained. New static routes for PE integration: /ui/chart-ui.js, /ui/research.js, /ui/research-ui.js, /ui/research.css.

Author actual-entry checks:21 focused JS tests; syntax checks; at1440 and390 pixels, actual old API404/unavailable state plus clearly INVENTED_CONTROL intercepted records tested second-question selection, negative criteria, undefined control Sharpe, initial NOT_APPLICABLE return, gap/zero preservation, exact ledger and light/dark. The registered view preserved AAPL/1M pinned points2746→2747 when switching to unavailable research and back. Both local fonts loaded. These are author checks, not actual persisted research or independent Stage2 acceptance. Network interceptions removed and own browser closed; preview retained for assigned QA.

Next dependency is PE normal CI/integration/static routes and actual qualified saved-result API plus persisted IDs. Stage2 remains NOT RUN. QA should preserve Stage1 covered effects and check affected shared navigation/narrow header/return continuity with Stage2, not replay the entire chart path. No guessed curves, client finance or demo fallback. Fixed final deadline2026-11-10T04:13:01.062Z.
