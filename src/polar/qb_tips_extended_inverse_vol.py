"""One fixed TIP-expanded inverse-volatility cohort, unchanged common mechanism."""
from .qb_common_risk_inverse_vol import profile as base_profile
from .scheduled_policy import profile_value

PROTOCOL_ID = 'QB-TIPS-EXTENDED-INVERSE-VOL-20261118-V1'
SYMBOLS = ['BIL', 'SHY', 'TIP', 'TLT', 'VTI']


def profile(*, protocol_sha256, input_sha256, calendar_sha256, timezone_sha256):
    p = base_profile(protocol_sha256=protocol_sha256, input_sha256=input_sha256,
                     calendar_sha256=calendar_sha256, timezone_sha256=timezone_sha256)
    previous = p['primary_strategy']
    p.update(protocol_id=PROTOCOL_ID, symbols=list(SYMBOLS), primary_strategy='INV',
             question_label='Fixed TIP-expanded inverse volatility at common forecast risk',
             question_summary='Does the fixed expanded inverse-volatility cohort meet the entire net wealth, material Sharpe, drawdown and realized-risk screen against its new equal-weight and momentum controls in both cost cases?',
             clock_description='Causal formation prefix; modeled next New York midnight plus one second, next declared reference close and terminal exit override.',
             partition_description='Inherited exposed retrospective FINAL calendar and prefix unchanged. No period replacement, untouched validation or selection-adjusted confirmation.',
             additional_limitations=[
                 ['FIXED_REFERENCE_UNIVERSE_EXPANSION','Only the fixed bill, short and long nominal Treasury, TIP and equity vendor-reference paths. Inflation protection or economic continuity is not assumed; qualified source fit remains separate from this profile.'],
                 ['NEW_CONTROLS_AND_FORECAST_RISK','Every control and common forecast-risk target is formed anew on the expanded cohort. Previous cohort accounts and scores are not controls; whole units, fees, clipping, drift and realized risk remain distinct from targets.'],
                 ['EXPOSED_SOURCE_AND_CUSTODY_LIMITS','Selected after exposed prior findings; source, PIT, vintage, continuity, investor total-return, availability, rights and custody FAIL/UNKNOWN plus test/reviewer histories remain. Conditional saved-return resampling is not population, causal, untouched or selection-adjusted evidence.'],
             ])
    for leg in p['legs']:
        if leg['id'] == previous:
            leg['id'] = 'INV'
    for criterion in p['criteria']:
        if criterion['left_id'] == previous:
            criterion['left_id'] = 'INV'
        if criterion.get('right_id') == previous:
            criterion['right_id'] = 'INV'
    return profile_value(p)
