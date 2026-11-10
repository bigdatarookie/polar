# Failed OBS158 preflight diagnostics

The existing admission assertion and error `OBS158_DATA_PREFLIGHT_DISALLOWED`
remain unchanged. On a failed data check, service errors retain a bounded
`preflight_diagnostic`: all original check codes, statuses, reasons, required
flags and evidence bases, including engineering NOT_RUN. The diagnostic is
limited to64 closed check records with bounded uppercase identifiers. It does
not include raw source rows, prices, source context, physical paths or bindings.
Unexpected diagnostic metadata is UNAVAILABLE without replacing the original
admission failure.

The existing obs158-preflight CLI still exits1 and emits an obs158-error/1 on
stderr, now including this metadata. The owning operator must retain stderr in
the same private attempt evidence location. No artifact-store attempt, original
budget debit, native run, replay or retry is created by preflight. If a run has
already conservatively recorded a start and then fails preflight, its ordinary
failed finish also retains the diagnostic; its start is not refunded or reset.

This source correction does not identify the predicate in a historical generic
failure. The original failed preflight and empty store remain immutable. Any
later diagnostic consumption requires the actual qualified source/config/runtime
binding and the existing retained executor's authority; no source, universe,
date, threshold, price or scientific-exam change is authorized here.
