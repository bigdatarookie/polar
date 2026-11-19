# IEF/BIL private descriptor

The native operation implements the frozen `IEF-BIL-EQUITY-DOWN-MONTH-01` protocol against the qualified immutable IEF, BIL and VTI source. The descriptor keeps exact rational values and the monthly review trace in an owner-only artifact. Source preflight still returns structural metadata, and generic research loaders still reject the selected source.

## Native authority and runtime

Engineering Lead returns the original outcome task `qitem-20261119225310-1632c5a0` directly to `quant-a@polar-rig` using the native atomic handoff-and-complete operation. The new task retains the project, mission and slice tags. Its body is the JSON object built by `ief_bil_descriptor.authority(config)`, with the accepted checkout revision, actual compatible image, private output path and frozen input and protocol pins. Quant A claims that task in the live seat and uses its ID as `consumer_task`. Data Researcher’s qualification and the terminal Engineering Data receipt establish source provenance separately.

Run from the same clean accepted checkout on host and guest. Use the previously qualified runtime image, Linux Python 3.13.18, UID 10001, a fresh task-private `PYTHONPYCACHEPREFIX`, and `PYTHONDONTWRITEBYTECODE=1`. Start the container with network disabled. Mount the original source store read-only at its existing guest path and preserve its guest root identity. Keep the protocol, source metadata and receipt mounts read-only at their pinned absolute paths. The dedicated output is the only writable Docker mount, including when source or metadata paths have alternate bind destinations. Bind the source store and output directory at their identical host and guest paths. Use the dedicated writable `descriptor-store` directory beside the original `store`, owned by the runtime UID with mode `0700`, and set it as `POLAR_ARTIFACT_ROOT`. Use the allocation supported by `Settings.load_artifacts()`.

The closed config schema is `polar.ief-bil-private-descriptor-config/1`. Set `namespace` to `RETAINED`, `question_id` to `IEF-BIL-EQUITY-DOWN-MONTH-01`, `purpose` to `research-ief-bil-descriptor`, and `actor_session` to `quant-a@polar-rig`. Pin the frozen protocol, original `INPUT-REF.json`, and Data Researcher’s correction receipt as `protocol_ref`, `locator_ref` and `qualification_ref`. Each ref carries the absolute path and SHA-256, optionally the byte length. Derive `code`, `code_revision`, and `artifact_root_identity` inside the actual guest using `gym_service.code_binding()`, `candidate_binding.loaded_revision()`, and `ci_research_service.root_identity()`. Set `runtime_image_id` to Docker’s observed image ID and expose the same ID as `POLAR_RUNTIME_IMAGE_ID` inside the guest.

```sh
python -m polar.native_selected_tool --container HEXCID \
  --operation research-ief-bil-descriptor CONFIG.json
```

## Private effect

A successful native reply gives the question, effect ID, status and the pinned `checkpoint.json`. The checkpoint binds the scope, immutable source, accepted runtime and current claim, and pins the sibling `descriptor.json`. The descriptor stores exact fractions as decimal numerator and denominator strings, phase and subset summaries, the contrast, both anchors and the ordered paired-month trace. An empty down-month subset and its contrast are `NOT_EVALUABLE`.

Use the same authorized config and root when reconciling a lost reply. A complete matching effect returns the same checkpoint without a quote read or recalculation. A different binding, incomplete effect or staged publication requires reconciliation of the preserved directory before any further attempt. Keep the source, descriptor and review material private within the documented noncommercial and reference-data limits. Quant A owns empirical execution and interpretation, with independent scientific review.
