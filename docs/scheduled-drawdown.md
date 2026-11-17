# Quant A drawdown policy in the existing scheduled runner

Profile `polar.scheduled-reference-profile/14` statically imports
`research_candidates.quant_a_drawdown_gate.policy`. The policy bytes are unchanged
from author candidate `957447a203d7fca6c99b5854b47a51791954c438`; their SHA256 is
`974bc78fea2d0495d213d361abf257a31ebd05f63b9197061a0a2c490a909a2c`.
The original candidate directory remains untouched. Copied README/config retain
their historical statuses; that policy-only config is not a runtime seed.

The adapter uses dated Fraction closes through formation only. Observed risk
state is independent of fills. First eligible observation or a state change
produces rational TARGET; unchanged state or insufficient history produces HOLD.
No monthly targets are added to the gate. The controls are initial-only full
VTI, initial and monthly half VTI/half BIL, and initial-only full BIL. Terminal
EXIT, fee clipping, quantities and execution remain with the common reference
ledger. One plan per phase is frozen after FIRST_START and reused for BASE and
doubled-cost accounts. The three frozen point criteria apply to FINAL; validation
is diagnostic. Design history, the exposed 2021-01-04..2022-12-30 validation context
and 2023-01-03..2026-11-06 final/evaluation interval retain their author meanings;
none is called an untouched holdout. Both operational phases are required for
retained execution. The existing daily-gate calendar/1 supplies dated formation
and next reference execution; timezone is UTC and decision delay is sixty seconds.

The profile policy object is exactly:

```json
{"kind":"QUANT_A_DRAWDOWN_RECOVERY","semantic_candidate":"957447a203d7fca6c99b5854b47a51791954c438","policy_sha256":"974bc78fea2d0495d213d361abf257a31ebd05f63b9197061a0a2c490a909a2c"}
```

Leg IDs/rules are DRAWDOWN_GATE/DRAWDOWN, FULL_VTI/FULL_VTI,
FIXED_HALF/MONTHLY_HALF and FULL_BIL/FULL_BIL, each scale [1,1]. The primary
strategy/benchmark are DRAWDOWN_GATE/FIXED_HALF. Criteria in order are DRAWDOWN_LE
versus FIXED_HALF, TERMINAL_GE versus FIXED_HALF, POSITIVE_GROWTH. Costs remain
BASE flat100 cents/bps10 and COST_STRESS flat200 cents/bps20. Other common profile
fields, source/protocol/calendar/timezone hashes and result schema are unchanged.
The loaded code binding includes the exact external policy path/hash, static
adapter and registration. A mismatched/missing policy, foreign import, dirty
external source or wrong composed Git revision fails closed.

## Selected input and actual native context

Conversion config/7, profile QUANT-A-DRAWDOWN-SELECTED-INPUT-V1, binds the actual
composed candidate, semantic author candidate, full code binding, actual runtime
image, current native Quant A task/generation, exact source pins, protocol/purpose
and purpose-fit pins, and the existing private artifact-root identity. It adds
no source permission: the source semantic decision is still Quant A's and is
NOT_ISSUED until actually made. No Operator/Lead execution grant is introduced.

Config fields are schema, profile_id, namespace, semantic_candidate,
code_revision, code, runtime_image_id, consumer_task, source_admission_ref,
artifact_root_identity, purpose_ref, purpose_fit_ref, protocol_ref,
vti_binding_ref, vti_parent_ref, bil_input_ref and operation. Operation is exactly
SELECTED_INPUT_PREPARE_AND_READ. Pins retain absolute resolved nonsymlink paths
and original SHA256/optional bytes. The selected graph uses the qualified BIL-only
leaf and the existing VTI binding's exact normalized segments, partition and
collection metadata. Mixed B10/BIL-SHY/VTI-parent quote files are not read.
Only VTI-selected normalized spans are JSON-decoded. All member bytes used for a
hash can include excluded spans; no semantic validation of those excluded spans
or full-parent contents is claimed. Raw source bodies are not reopened: original
pointers/body hash metadata are preserved, not newly certified source extraction.
Retained profile14 requires this selected converter and matching source/author
build/protocol/private namespace in the shared scheduled preparation path before
FIRST_START or value reads, including ordinary Service/CLI calls. The context
wrapper is optional transport, never the admission boundary. The existing output
input/2 reader rechecks native context before loading this
prepared projection. Legacy profiles and their readers retain their behavior.

`source_admission_ref` addresses a real terminal Quant A decision. Its resolution
must be exactly the following typed object with actual values (placeholders below
are a contract, not an issued admission):

```json
{"schema":"polar.native-selected-source-admission/1","status":"ADMITTED_WITH_LIMITS","consumer_task":"ACTUAL_CURRENT_QITEM","claimed_generation":"ACTUAL_GENERATION","scope_sha256":"SHA256_OF_HISTORY_CANONICAL_CONFIG_WITHOUT_SOURCE_ADMISSION_REF","symbols":["BIL","VTI"],"scientific_verdict":"NOT_REVIEWED"}
```

The native tool verifies current assigned Quant A identity, claimed task,
transport claim/terminal actors, generation, full config binding and rereads
custody. Current generation comes from the bounded read-only `rig ps --nodes`
projection for the actual Quant A seat. Its generation provenance must be
resolved, current and nonfallback, from a verified native owner or a hook checked
against the occupant tenure at read time. Resolved-but-stale mismatch is rejected.
The live generation must match the owned active consumer task and terminal source
decision, and it is read again before return. No claim/unclaim/reclaim is used;
claiming an already-active task is rejected by the actual daemon.
A body actor string, readable host path, metadata fit receipt or an old
source decision is insufficient. Purpose/source admission remains a real consumer
condition, never inferred from technical tests.

Normal positional CLI remains `research-input-prepare CONFIG.json`, then
`research-input-preflight MANIFEST_PIN.json`; author `research-config SEED.json`,
`research-preflight CONFIG.json`, `research-run CONFIG.json` retain the existing
engine/attempt/history path. Missing execution_authority_ref uses accepted
ordinary automatic offline binding. No financial execution is performed by this
implementation's tests on retained data.

Where the exact author container has no rig binary, the existing stdio adapter
also supplies current context through a bounded closed companion:

```text
python -m polar.native_selected_tool --container HEXCID --operation research-input-prepare CONFIG.json
python -m polar.native_selected_tool --container HEXCID --operation research-input-preflight MANIFEST_PIN.json
python -m polar.native_selected_tool --container HEXCID --operation research-preflight RUNTIME_CONFIG.json
python -m polar.native_selected_tool --container HEXCID --operation research-run RUNTIME_CONFIG.json
```

This is a context transport into the same existing file-only Service operations,
not a new runner. The last two accept only registered profile/14. The host and
container must load the exact same source binding. Every native read is live on
the inherited host transport, restricted to reads of the consumer/admission tasks, Quant A seat and exact
current-generation projection, bounded to32 reads/2MiB frames/600seconds. No identity, provider,
credential or service is installed in the container. The container's actual
image, mounted source/data/private-store paths and root identity must match the
admission; host filesystem readability alone is not container data-plane proof.
Missing actual admission, qualified mount/build or current native caller remains
a typed error. Only the author may perform the eventual admitted private prepare,
preflight and backtest. G rollout, Quant B and UI/Infrastructure acceptance remain
independent of this source milestone.


Before issuing a source decision, the author can verify its actual current native
context without any source, protocol, store or value access:

```text
python -m polar.native_selected_tool --container HEXCID --operation native-context-probe CONSUMER_TASK.json
```

CONSUMER_TASK.json contains only `{"consumer_task":"ACTUAL_OWNED_ACTIVE_QITEM"}`.
The probe checks the same current actor/task/claim provenance and read-only live
generation used by preparation, then rereads custody. It returns
CURRENT_NATIVE_CONSUMER_CUSTODY_VERIFIED with NOT_ISSUED_BY_PROBE; it does not mint
admission, inspect source pins, load Settings/store or record FIRST_START. It
uses the same bounded inherited host/stdin bridge and source fingerprint. A
provisional source-decision row closed with NOT_ISSUED is never an admission.
Rebuild/pin the corrected actual author candidate and image before source
admission; preserve earlier qualified build and boundary failure history.
