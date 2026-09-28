"""Batch 13: a checkpoint log keeps its parsed index and reads only what was
appended. It must still see every change another writer makes, and the chain
verification must never trust the cache."""
import pytest

from athenaeum_body.storage.checkpoint import ChainIntegrityError, CheckpointLog
from athenaeum_body.storage.content_addressed import ContentAddressedStore


def logs(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    return (CheckpointLog(cas=cas, index_path=tmp_path / "i.txt"),
            CheckpointLog(cas=cas, index_path=tmp_path / "i.txt"))


def test_another_writer_s_appends_are_seen(tmp_path):
    a, b = logs(tmp_path)
    a.write_checkpoint({"n": 1})
    assert b.read_latest() == {"n": 1}
    a.write_checkpoint({"n": 2})
    assert b.read_latest() == {"n": 2} and len(b._read_index()) == 2
    b.write_checkpoint({"n": 3})
    assert a.read_latest() == {"n": 3} and a._read_index() == b._read_index()


def test_a_half_written_line_waits_for_its_end(tmp_path):
    a, _ = logs(tmp_path)
    first = a.write_checkpoint({"n": 1})
    with (tmp_path / "i.txt").open("a") as f:
        f.write("sha256:half")                          # another process, mid-write
    assert a._read_index() == [first]
    second = a.write_checkpoint({"n": 2})               # appends after the partial text...
    assert a._read_index()[-1] == "sha256:half" + second   # ...exactly as the file now reads


def test_an_index_rewritten_in_place_is_read_again(tmp_path):
    a, _ = logs(tmp_path)
    h1 = a.write_checkpoint({"n": 1})
    h2 = a.write_checkpoint({"n": 2})
    assert a._read_index() == [h1, h2]
    (tmp_path / "i.txt").write_text(f"{h2}\n{h1}\n")     # same size, reordered
    assert a._read_index() == [h2, h1]


def test_verification_never_trusts_the_cache(tmp_path):
    a, _ = logs(tmp_path)
    h1 = a.write_checkpoint({"n": 1})
    h2 = a.write_checkpoint({"n": 2})
    a._read_index()
    (tmp_path / "i.txt").write_text(f"{h2}\n{h1}\n")
    a._index_cache["last"] = f"{h1}\n".encode()         # even a cache that looks current
    with pytest.raises(ChainIntegrityError):
        a.verify_chain()


def test_a_truncated_index_is_read_in_full(tmp_path):
    a, _ = logs(tmp_path)
    h1 = a.write_checkpoint({"n": 1})
    a.write_checkpoint({"n": 2})
    (tmp_path / "i.txt").write_text(f"{h1}\n")
    assert a._read_index() == [h1] and a.read_latest() == {"n": 1}
