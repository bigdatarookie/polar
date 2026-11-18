"""Static frozen author assets for the closed native account Band path."""
import hashlib
from pathlib import Path
from research_candidates.quant_a_vti_bil_band import policy as author
from .ci_research import require

QUESTION = 'VTI-BIL-NO-TRADE-BAND-01'
POLICY_SHA = '014d219579346ff8c2a11873ae2143543723de8498d048d3bf3c56d411bcccbd'
CONTRACT_SHA = '25e32d4b87e3ead3553d2c63f604ff04e435972bc2c097665ca35730c5f4466d'
PROTOCOL_SHA = '404dc1dfc13c4ad523aac50d5a4b88021bc3a642ecb6bb292e1032237b70df03'
AUTHOR_CANDIDATE = '3b11851a5b1eaf5e7f64d8f1639aafe6fdedfea2'
POLICY_PATH = 'research_candidates/quant_a_vti_bil_band/policy.py'
IDS = ('BAND_HALF','MONTHLY_HALF','HOLD_INITIAL_HALF','FULL_VTI','FULL_BIL')
COSTS = [{'id':'BASE','cost_profile':{'flat_cents':100,'bps':10}},
         {'id':'COST_STRESS','cost_profile':{'flat_cents':200,'bps':20}}]


def policy_binding():
    root=Path(__file__).resolve().parents[2]
    require(Path(author.__file__).resolve()==root/POLICY_PATH,'BAND_STATIC_IMPORT')
    result={}
    for name,digest in [('policy.py',POLICY_SHA),('author_contract.json',CONTRACT_SHA),('protocol.md',PROTOCOL_SHA)]:
        path=root/'research_candidates/quant_a_vti_bil_band'/name
        require(not path.is_symlink() and path.resolve()==path and hashlib.sha256(path.read_bytes()).hexdigest()==digest,
                'BAND_AUTHOR_BLOB')
        result[str(path.relative_to(root))]=digest
    return result
