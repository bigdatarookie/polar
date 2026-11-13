# Closed B9 fixed parking adapter

Profile `polar.scheduled-reference-profile/12` reuses the existing fixed annual
calendar, REFERENCE_TARGETS native ledger, NEXT_CLOSE executor, immutable store,
`evaluate_legs` eighteen scalars, and common private/local result. It admits only
BIL_FULL, SHY_FULL and CASH with full BIL, full SHY and zero cash-control weights;
BASE USD1+10bps and fresh doubled USD2+20bps accounts. There is no fitted policy,
new engine, source capture, cash yield, extra action credit or public rollout.

The five ordered clauses are exact terminal wealth >=9/10 SHY, canonical D50 BIL
Sharpe >=0, exact drawdown <=1/2 SHY, fresh D50 volatility <=SHY/2 and positive
net growth. Structural invalid account/initial/terminal/grid state rejects before
scalar screening. In a valid phase, known NOT_MET takes precedence over another
UNAVAILABLE; otherwise missing required metrics make the point indeterminate.
SHY/CASH Sharpe and CAGR are report-only. Zero drawdown/volatility remain zero,
without a ratio division. This does not change the legacy profiles' criteria or
status precedence. Financial review remains independent; source or technical
success cannot establish support, adoption or robustness.

The profile uses unchanged fixed TARGET/HOLD/EXIT timing and source scale1, whole
synthetic reference units. It opts into existing native sizing and fee-aware
order call-site capture under `polar.fixed-reference-consumed-operands/1`.
The saved verifier binds each D cash/holdings/eligible price/NAV/floor and every
pre-order cash/holdings/quote/fee clip/maximality/zero reason/fill ID, plus native
mark dates/clocks/holdings/NAV, each rounded position amount and total exposure,
per-mark accumulated flat/bps costs, exact fill notional and rounding residuals. The unit is WHOLE_SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE;
there is no coarse100 mapping. Saved verification checks the fixed calendar and
saved metadata/operands without source, policy or native invocation, and never
backfills absent prior witnesses. Existing `ReferenceResearchService.recompute`
checks both saved cost phases with no source/native/store write.

The existing offline `reference_input.prepare_input` gains one closed captured
BIL branch, config `polar.reference-input-conversion-config/4`, profile
`CAPTURED-BIL-ADJUSTED-REFERENCE-INPUT-V1`. Required fields are schema, profile_id,
namespace, capture_return, exact_tokens, purpose, schedule, date_range. Refs retain
absolute path, SHA256 and byte length. Purpose schema is
`polar.captured-reference-source-purpose/1` and has capture_return, exact_tokens,
symbols=[BIL], schedule, date_range, consumer_protocol, source_acceptance,
rights_source_refs and rights. consumer_protocol pins a separate JSON
`polar.captured-reference-protocol-binding/1` containing protocol and packet pins;
protocol Markdown bytes are verified, while packet JSON is decoded.

The bridge checks the actual single-GET receipt, HTTP200 and complete body length,
original SIP/USD/1Day/all request, exact original body tokens and DE-derived token
pointers. It preserves original `/bars/BIL/i/c` and separate `/rows/i/tokens/c`
object scopes. Positive lossless BIL closes have at most2 fractional digits and
are zero-padded to6, never rounded or rescaled. The capture is not an importer
collection/job; none is fabricated. New source_ref kind
CAPTURED_ALL_ADJUSTED_SOURCE binds the original capture/body/token/pointer graph.
Historical publication/availability/source version stay unknown. Source amount
reads occur only on explicitly admitted converter use, not metadata preparation.

Output is existing synthetic-reference-source-input/2. Existing config3 composes
it with a selected SHY input while preserving separate source_capture versus
source_collection and all source pointers. It establishes no common vintage,
PIT availability, physical shares, source-independent performance or financial
fitness. Actual DE source acceptance/current purpose, independent qualification,
accepted runtime and existing operation custody remain required before retained
use. No provider call, secret/account change, automatic retry or scientific grant
is part of this source package.

Explicit fixture-mode or deterministic-invented/NONE provenance metadata is
rejected in the RETAINED capture namespace before numeric values are opened.
The actual retained single-GET capture plan has no mode field; absence or provider
mode is permitted with its independently pinned observed capture metadata.
No historical importer mode or collection is invented to satisfy this guard.
