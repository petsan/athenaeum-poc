import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore, IntegrityError, NotFoundError

def test_put_get_roundtrip(tmp_path):
    cas = ContentAddressedStore(tmp_path)
    key = cas.put(b"hello world")
    assert cas.get(key) == b"hello world"

def test_dedup(tmp_path):
    cas = ContentAddressedStore(tmp_path)
    k1 = cas.put(b"same content")
    k2 = cas.put(b"same content")
    assert k1 == k2

def test_tamper_detected(tmp_path):
    cas = ContentAddressedStore(tmp_path)
    key = cas.put(b"original")
    cas.corrupt_for_testing(key, b"tampered!")
    with pytest.raises(IntegrityError):
        cas.get(key)

def test_missing_key(tmp_path):
    cas = ContentAddressedStore(tmp_path)
    with pytest.raises(NotFoundError):
        cas.get("sha256:" + "0"*64)
