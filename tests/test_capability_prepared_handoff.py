"""Offline publication/reference boundary only; no worker or runtime invocation."""
import pytest

from polar.capability_contract import CapabilityError, canonical, sha
from polar.capability_runtime import prepared_input_ref
from polar.capability_store import immutable


def test_worker_publication_is_referenced_without_second_writer(tmp_path,monkeypatch):
    prepared={'schema':'polar.capability-prepared-native/1','invented':[1,'0.10']}
    published=immutable(tmp_path/'prepared-native.json',prepared)
    before=(tmp_path/'prepared-native.json').stat()
    def forbidden(*args,**kwargs):
        pytest.fail('runtime must not publish another prepared input')
    monkeypatch.setattr('polar.capability_runtime.immutable',forbidden)
    reference=prepared_input_ref(tmp_path,prepared)
    assert reference==published
    assert reference['sha256']==sha(canonical(prepared))
    assert (tmp_path/'prepared-native.json').read_bytes()==canonical(prepared)
    assert (tmp_path/'prepared-native.json').stat().st_ino==before.st_ino
    assert sorted(p.name for p in tmp_path.iterdir())==['prepared-native.json']


def test_runtime_rejects_a_different_prepared_payload(tmp_path):
    immutable(tmp_path/'prepared-native.json',{'invented':1})
    with pytest.raises(CapabilityError,match='INPUT_INTEGRITY'):
        prepared_input_ref(tmp_path,{'invented':True})
