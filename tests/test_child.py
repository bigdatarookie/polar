"""Exercise the real supervised calculation/publication child without a DB mock."""
import multiprocessing as mp
import uuid

from polar.artifacts import ArtifactStore
from polar.worker import compute_child


def test_real_child_publishes_fixed_result(tmp_path,data,config,raw_fixture):
    ctx = mp.get_context("spawn")
    recv,send = ctx.Pipe(duplex=False)
    run_id,aid = uuid.uuid4(),uuid.uuid4()
    process = ctx.Process(target=compute_child,args=(send,data.model_dump(mode="json"),
        config.model_dump(mode="json"),tmp_path,1024**2,run_id,aid,
        {"source_sha256":"a6dd88480836e262c565f1ba4dfd5a056e7bbfd1688787dd2a343a82bf0bba14",
         "original_dataset_utf8":raw_fixture.decode(),"imported_at":"actual-test-time"}))
    try:
        process.start()
        send.close()
        assert recv.poll(10), "Child calculation/publication did not finish within 10s"
        result = recv.recv()
        assert "error" not in result
        process.join(timeout=2)
        assert process.exitcode == 0
        report = ArtifactStore(tmp_path).report(result["artifact_ref"])
        assert report["nav"][-1]["nav"] == "1014"
        assert result["cpu"] > 0
    finally:
        if process.is_alive():
            process.kill()
            process.join(timeout=2)
        recv.close()
        send.close()
