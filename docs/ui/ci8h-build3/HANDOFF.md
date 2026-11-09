# Polar frontend refinement

Owned branch build3/ci8h-ui-20261109, isolated from accepted ad20035efdd972778c0b1f48f43bf51f935a48d1. Backend/common runner/serving remain PE/SRE owned.

## Chart stage

- Data details native disclosure retains exact raw values/statuses. Calculation/source details are on demand in the rail. At narrow widths data disclosure precedes the scrollable plot for immediate access.
- Volume toggle releases its pane height and intervening gap to candles; RSI/reference axes remain attached to the same timeline. Volume and disclosure preferences persist; Reset restores volume on/details closed.
- Overlay card samples and ECharts strokes share chart-ui.js definitions, including all three BB lines and both reference lines. No new assets or SVGs.

Author checks: node --test tests/ui_components.cjs tests/ui_chart_refinements.cjs (15 passed); app/chart-ui syntax; actual AAPL/1M/Light/all overlays at1440x900 and390x844. Exact baseline had7 pre-existing component-test failures: stale VM script dependencies and retained-mode/control/error expectations were repaired in the allowed harness. No production semantics were changed to satisfy them.

Preview http://127.0.0.1:18983/ui/ uses owned static frontend and GET-only upstream18081. SRE20:30 current upstream is accepted0cd2e1f/tree989d9c32, CID2fe3fd57. It is not the new research backend. Preview PID40861, born2026-11-09T20:30:01.822Z; no backend/source lifecycle action. Useful images are outside Git at state/build/ci8h-build3. Independent Stage1 QA pending; author checks are not independent acceptance.

## Public controls / reset

Default Stored history mode, first registered asset; reset uses actual catalog. Match baseline1440x900, Light(Settings), AAPL,1M, Overlays SMA20/EMA20/BB20k2/RSI14/reference. Wait for Context ready after each asynchronous request. Volume is a pressed button in legend. Data details summary toggles exact raw text; calculation disclosure follows each overlay's periods/sample. Chart focus + Enter pins/clears; arrows move selected point; Escape clears. Real history and retained test mode remain explicitly separate.

## Saved research

Wire-v1.1 frozen fields consumed, actual implementation/data pending. No guessed curves, locally computed finance or demo fallback. Existing chart stage can be checked independently while this is implemented. Fixed final deadline2026-11-10T04:13:01.062Z.
