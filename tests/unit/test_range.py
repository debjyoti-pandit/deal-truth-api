from app.storage.memory import MemoryBlobStore


def test_range_request_handling() -> None:
    store = MemoryBlobStore()
    payload = b"ABCDEFGHIJ"
    store.put_bytes("audio", "k", payload, "audio/wav")
    obj = store.download_stream("audio", "k", range_start=2, range_end=5)
    assert obj.body.read() == b"CDEF"
    assert obj.size_bytes == 10
    full = store.download_stream("audio", "k")
    assert full.body.read() == payload
