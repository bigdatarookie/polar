from types import SimpleNamespace
import pytest
from polar.capability_contract import CapabilityError
from polar.capability_runtime import ObservedRuntime


def test_reobserved_periodic_receipt_after_final_does_not_rollback_charge():
    r=SimpleNamespace(worker_cpu=873371,worker_sample_cpu=873371,native_ns=67026999)
    r.worker_cpu=897718;r.native_ns=100880040  # actual retained final receipt
    ObservedRuntime.sample_usage(r,{'cpu_us':873371,'native_wall_ns':67026999})
    assert r.worker_cpu==897718 and r.native_ns==100880040
    ObservedRuntime.sample_usage(r,{'cpu_us':873371,'native_wall_ns':67026999})
    assert r.worker_cpu==897718


@pytest.mark.parametrize('value',[873370,True,-1,'873371'])
def test_real_periodic_regression_or_bad_type_still_rejects(value):
    r=SimpleNamespace(worker_cpu=897718,worker_sample_cpu=873371,native_ns=100880040)
    with pytest.raises(CapabilityError,match='INTERNAL_EXECUTION_ERROR'):
        ObservedRuntime.sample_usage(r,{'cpu_us':value,'native_wall_ns':67026999})
    assert r.worker_cpu==897718 and r.worker_sample_cpu==873371
