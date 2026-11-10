# v033 buffered chart author handoff

## Outcome and scope

Price-history viewport movement commits locally. It never dispatches the previous bounds while waiting for indicators. For the currently admitted daily asset (2,770 dates), all candles and necessary server-calculated series load into a complete validated buffer; wheel/preset movement does not request series. Pending indicator parameters retain coherent previous values, with an explicit local loading/unavailable label. A same-context series response remaps and preserves the latest viewport and measurement dates rather than restoring request-time bounds.

Cache identity includes dataset revision/receipt/manifest/basis, instrument, interval, all indicator controls/parameters, reference family, benchmark, calculation/numeric versions and definition hash. Completed validated buffers only; four-entry LRU. Identical pending requests coalesce. New contexts/parameters cancel obsolete work, and aborted responses cannot commit or enter cache even if transport ignores abort. Partial pages never commit. No client indicator/finance calculation, curve substitution, backend or dependency changes.

## Live draft and provenance

First frozen draft: `ee1a28c26dc477c528e86a57fde85a91b69c2adb`, tree `9faab7b13c795016da959df2292fa20610e9f4c6`, http://127.0.0.1:18984/ui/ . Own GET-only static/proxy PID83435, birth2026-11-10T11:17:40.321Z. Upstream http://127.0.0.1:18081 . Source snapshot and useful evidence: `/Users/garry/.openrig/shared-docs/rigs/ui-team/state/build/v033-chart-build3/`. Original bootstrap PID81128 was stopped after exact PID/command/birth check before freezing snapshot. Actual accepted serving is unchanged.

Real dataset `history-private-us-demo-01`, revision `histrev-8513a1cfd4042eca2da45051ed8a1f14ac62b19bdb14ef7d7ad05fc0d65bddae`, AAPL `hist-us-0001`, 1D RAW_CLOSE. Series retains backend full-prefix/warmup metadata; visible range does not reseed EMA/RSI/reference. Existing ECharts6 canvas chart is an interactive control/workspace anchor. No new SVG/image/font assets; accepted provenance/fonts preserved.

## Reproducible controls

Enter Price history, stored AAPL. Open Overlays; enable SMA20, EMA20, BB20 deviation2; wait Context ready. Select1M. At1440x900 wheel over plot approximately800,360; alternating deltaY±144 shifts four observations. Range presets, slider/drag, cursor/measurement and asset picker remain live. Indicator period buttons are `#sma-period-5`, `#sma-period-50`, etc. Checkboxes `#sma-toggle`, `#ema-toggle`, `#bollinger-toggle`, `#rsi-toggle`, `#benchmark-toggle`; plot `#chart-stage`. Refresh retains current context; Reset returns accepted defaults. Saved research/nav/table keyboard behavior is unchanged and is not another finance/journey replay.

## Browser observations and timing limits

Accepted18081 rollback reproduced before editing: wanted2745..2768; first RAF15.6ms still rendered/committed2741..2764 with loadingtrue. Actual series fetch headers arrived537.5ms after start (headers only, not full request/paint). `baseline-motion.json`, baseline screenshot retained.

Draft ee1a28c author measurement: raw `draft-motion-samples.json` contains31 events. Exclude initial spotcheck `samples[0]`; measured subset `samples[1:31]` is30 alternating actual CLI wheel±144 inputs with two RAF settlement before next input. Window capture listener timestamps input (stage stops propagation); next RAF reads ECharts dataZoom bounds and committed state. All30 moved and matched; zero series GETs, zero observed long tasks. Nearest-rank percentile uses sorted index `ceil(.95*n)-1`: p95 **8.3ms**, median5.3ms, max29.2ms. Earlier progress message8.1ms used floor order statistic and is superseded. All31 nearest-rank p95 is also8.3ms. This is input-to-first-RAF matching rendered/committed bounds, **not direct display-paint timing** or a universal device guarantee. HeadlessChrome157, macOSIntel UA,1440x900,DPR1,14 logical cores. CLI process duration is excluded. No contention/throttling control was asserted.

A task-owned fetch wrapper delayed actual SMA50 responses1200ms and deliberately ignored abort; no substituted response/data/backend change. During loading a real wheel moved2746..2769 to2741..2764 and rendered2741, local label said indicators loading/candles remain interactive. Then SMA5 superseded it. `delayed-period-change.json` records final period5, current range retained, obsolete50 response settled without overwrite. This is scoped author evidence, not independent QA.

## Checks and remaining acceptance

Focused local Node checks:27/27 (22 accepted UI cases plus5 cache/cancellation/buffer cases). VM timer API shim adds clearTimeout; no weakened assertions. Official scripts/ci.sh selected UI projection + mandatory native + allNode is next; its external receipt will bind the immutable candidate. Independent QA1 existing affected journey owns runtime/adversarial/keyboard/narrow/performance result; no readiness claim before its return.

The accepted transport still rejects total candle profiles above5,000 rows (`HISTORY_ASSET_PROFILE_EXCEEDED`). No API/profile widening. Buffered-window helper and edge-prefetch support larger supplied contexts, with bounded margin; that >5,000 helper is a synthetic technical case, **not an actual admitted larger-history runtime claim**. Current actual per-instrument2770 dates is the full-buffer path. Network/cachemiss latency is separate from the in-buffer measurement; not quantified as a target guarantee.

Useful artifacts remain outside Git; no screenshots/diagnostic dumps committed. Own preview/browser cleanup occurs after assigned independent QA; preserve accepted18081 and unrelated resources.
