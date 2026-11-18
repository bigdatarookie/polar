"""Frozen covariance-aware equal-risk-contribution comparison."""
from copy import deepcopy
from .qb_equal_risk_contribution_prototype import PROTOCOL_ID
from .scheduled_erc import IDS, POLICY, SCHEMA, SPECS, SYMBOLS
from .scheduled_policy import profile_value


def profile(*, protocol_sha256, input_sha256, calendar_sha256, timezone_sha256):
    descriptions = {
        'TERMINAL_GT': 'Net terminal wealth must strictly exceed this common forecast-risk control.',
        'SR_DELTA_GE': 'Zero-risk-free Sharpe must exceed this control by the fixed material margin.',
        'DRAWDOWN_LE': 'Drawdown must be no worse than this control.',
        'VOL_RATIO_BETWEEN': 'Realized volatility must remain within the declared relative band.',
        'POSITIVE_GROWTH': 'Net terminal wealth must exceed initial capital.',
    }
    return profile_value({
        'schema': SCHEMA, 'protocol_id': PROTOCOL_ID,
        'protocol_sha256': protocol_sha256, 'input_sha256': input_sha256,
        'calendar_sha256': calendar_sha256, 'timezone_sha256': timezone_sha256,
        'symbols': list(SYMBOLS), 'policy': deepcopy(POLICY),
        'legs': [{'id': name, 'label': label, 'rule': name, 'scale': [1,1]}
                 for name, label in zip(IDS, (
                     'Monthly certified equal contributions to shrunk forecast variance',
                     'Monthly equal-weight common forecast-risk control',
                     'Monthly inverse standalone volatility common forecast-risk control'))],
        'primary_strategy': 'ERC', 'primary_benchmark': 'EW', 'decision_delay_seconds': 1,
        'cost_scenarios': [
            {'id':'BASE','cost_profile':{'flat_cents':100,'bps':10}},
            {'id':'COST_STRESS','cost_profile':{'flat_cents':200,'bps':20}}],
        'uncertainty': {'kind':'BASE_ONLY_PAIRED_SAVED_RETURN_CONDITIONAL_DESCRIPTIVE',
                        'block':63,'replicates':1000,'seed':37005},
        'criteria': [{'id':'criterion_'+str(i), 'description':descriptions[spec['kind']],
                      'left_id':'ERC', **spec} for i, spec in enumerate(SPECS)],
        'question_label':'Equal forecast-risk contributions versus standalone risk and equal weights',
        'question_summary':'Does the fixed covariance-aware risk-budget rule meet all net terminal wealth, material Sharpe, drawdown, realized-risk and positive-growth criteria against both controls in each cost case?',
        'clock_description':'Causal formation prefix only; modeled next New York midnight plus one second, next declared reference close, terminal exit override.',
        'partition_description':'Inherited exposed retrospective FINAL calendar and prefix unchanged. No untouched, causal, population or selection-adjusted confirmation.',
        'additional_limitations':[
            ['APPROXIMATE_RISK_BUDGET_EXACT_CERTIFICATE','The fixed Decimal coordinate method accepts only the exact relative-budget tolerance, not exact risk-contribution equality or exact numerical optimization. Original actual work remains distinct from saved verification.'],
            ['COMMON_FORECAST_GRID_NOT_REALIZED_RISK','Each maximal exposure grid index obeys the common shrunk-covariance variance bound. Whole units, clipping, fees, drift and realized risk differ from forecast weights; residual cash earns no interest.'],
            ['EXPOSED_REFERENCE_AND_SELECTION_LIMITS','Selected after exposed prior research, including negative findings. Vendor-reference units are not investor total return or funding. Source, PIT, vintage, continuity, rights, historical custody and exposure limits remain; paired saved resampling is conditional descriptive evidence only.'],
        ], 'subperiods':[],
    })
