# Trailing drawdown and recovery gate

This is a new author-owned long-only policy candidate, not a backtest result or
an installed strategy. It moves between VTI and BIL synthetic reference units
when VTI's eligible close crosses fixed trailing-peak drawdown/recovery levels.
It uses a 252-observation rolling peak, exits equity at 20% drawdown and returns
at 10% or less. The rolling peak can expire. No peak, threshold or window is
chosen from outcomes. Signal state is independent of holdings or fills.

The shared accepted runner must execute after formation/eligibility at the next
reference close. The policy never sees that execution price. Insufficient
history means HOLD; first eligible observation or a signal-state change means
TARGET. Unchanged signal state means HOLD. There is no leverage, shorting,
provider access, financial runner or platform change in this directory.

The proposed comparison uses full VTI, monthly fixed 50/50 VTI/BIL, and full BIL
on the same reference tape/ledger, initial capital and stated modeled cost
scenarios. These costs are assumptions, not measured historical execution.
The fixed screen is exploratory point evidence and is not a promise of
profitability or crisis protection. BIL is a modeled adjusted reference, not a
certified risk-free account. Do not add distribution/action credits to adjusted
closes or claim broker-share, investor total-return or historical PIT fitness.

Data purpose, exact source revision and prior trial/holdout exposure must be
resolved before reading protected values or running a backtest. Requested
chronological partitions do not establish an untouched exam. The old B9/B10
records remain immutable; their metadata-only reuse receipt grants no new
price access or experiment replay. A different admissible partition requires
an explicit pre-data config revision, preserving this initial candidate.

The accepted scheduled family already contains a temporal-volatility profile.
An initially considered volatility-cap idea was therefore not selected before
data or scoring. This candidate uses a different drawdown/recovery mechanism;
no temporal-volatility rerun or window retune is authorized by this directory.

Author unit checks use only invented controls. No source values, backtest,
scientific acceptance, publication or GitHub strategy PR is supplied yet.
Engineering owns the minimal existing runner/registration seam; it must use
the exact candidate checkout/build, not an older serving worker. Validator
receives a strategy PR only after the actual author backtest is complete.

Pre-data exposure revision: Data Researcher confirmed that B9/B10 already
observed the full requested historical interval. All proposed windows and
policy/cost/screen parameters remain unchanged. DESIGN, VALIDATION and
EVALUATION are descriptive segment labels for exposed retrospective analysis,
not pristine validation or an untouched exam. The new policy has not been
fitted on those values. Source-purpose mapping remains NOT QUALIFIED, so no
protected price read or backtest is admitted by this revision.
