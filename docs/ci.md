# Shared CI environment

Run the same technical command as an author or independent reviewer:

```sh
scripts/ci.sh
scripts/ci.sh --test tests/test_research_results.py --reports /tmp/polar-ci-my-check
```

`--source CHECKOUT` tests another exact Git checkout without modifying it. Repeat
`--test` to select several test paths or node IDs. An explicit selection still
runs the existing invented native Gym control; it does not quietly substitute
unit tests for native integration. With no selection, all Python tests run with
native Gym enabled, followed by the Node unit tests. Standalone headed browser
journeys are separate consumers and are not discovered as Node unit tests.

The command builds the environment directly from the public Docker recipe in
`.github/ci`, then creates an isolated PostgreSQL service and fresh test databases.
No hand-built image, host Python, QA package, assignment bundle or manual hash
matching is required. Docker must be available. The image is a build output and
can be cached; a pre-existing local image is not an admission requirement.

The official Python 3.13.18 and Node 24.22.1 multi-platform images are pinned by
manifest digest. All Python dependencies are public, version- and hash-locked,
including NautilusTrader 1.231.0, NumPy 2.2.6, SciPy 1.15.3 and LightGBM 4.6.0.
The CPU RL stack pins Stable-Baselines3 2.9.2, Gymnasium 1.4.0 and
PyTorch 2.15.0+cpu. Torch uses official, hash-pinned Python 3.13 CPU wheel
URLs selected for Linux x86_64 or aarch64, with no CUDA dependencies.
The same recipe supports Linux amd64 in Actions and arm64 locally. Regenerate the
lock with `uv pip compile .github/ci/requirements.in --python-version 3.13
--python-platform x86_64-unknown-linux-gnu --generate-hashes` and the equivalent
`aarch64-unknown-linux-gnu` target, constraining existing accepted versions.
Keep both explicitly marked Torch CPU wheel entries and verify other versions
and hashes agree across targets; review dependency changes as
part of the affected application change, without qualifying third-party libraries
as a separate project.

Reports include exact candidate SHA, dependency versions, executed commands,
JUnit results and explicit skips, bounded logs, exit/signal/timeout information,
and duration. Cleanup removes only the IDs created by this command and verifies
absence. Unknown cleanup fails the command. Test databases use disposable memory
storage; existing databases and volumes are not used. Reports remain on the host
after test containers are removed.

## GitHub Actions

`.github/workflows/ci.yml` runs on PRs and main pushes. It tests the current exact
revision and resolves the live head of a selected real product PR. The default is
PR49, the research-result API change. Earlier runs against frozen PR45 remain
failed evidence where they exposed the CLI/API timestamp defect; they are not
relabeled by the corrected workflow.

After this workflow is on main, select a current product PR with GitHub's native
manual dispatch:

```sh
gh workflow run ci.yml --ref main -f product_pr=49
# Optional affected scope; the native control still executes:
gh workflow run ci.yml --ref main -f product_pr=49 -f test_path=tests/test_research_results.py
```

Use the run's job results and downloadable `ci-<candidate>-<sha>` artifacts.
A commit status is attached to the exact selected candidate and links to the run;
workflow revision and tested candidate revision remain distinct. A green check
means only its named technical scope passed. Independent review still evaluates
changed code, controls, limitations and uncovered risks; it need not repeat an
identical local run merely to produce a second receipt.

## Private research

Actions tests only public or invented inputs. Do not mount or upload licensed
retained data, private oracle answers or credentials. Real research stays local
under its frozen protocol, source rights, candidate/trial accounting and separate
scientific authority. It uses the same official locked runtime with private
read-only inputs and task-owned outputs, through the application's ordinary CLI;
it does not require a legacy QA package or create new scientific authority.


## CPU RL runtime check

The existing command also runs a mandatory CPU-only import/API check and a
32-step PPO smoke on an invented 23-observation/five-action environment. It
checks one-thread execution, reset/step/predict and absence of CUDA, and records
versions and scope in `runtime-smoke.log` plus the ordinary result steps. This
qualifies library API compatibility; it does not qualify Polar's ledger, an RL
economic policy, a private training budget or financial performance. It downloads
no model or environment dataset. Application-specific synthetic tests remain
ordinary selections under the same command. Actual private training uses the
accepted source, frozen method and explicitly authorized private CLI/storage
scope; the toy smoke confers no authority to fit private data.
