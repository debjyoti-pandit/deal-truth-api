from app.core.job_ready import MemoryJobReadyWaiter


def test_memory_waiter_signal_before_wait() -> None:
    waiter = MemoryJobReadyWaiter()
    waiter.signal("job_a")
    assert waiter.wait("job_a", 0.1) is True


def test_memory_waiter_timeout() -> None:
    waiter = MemoryJobReadyWaiter()
    assert waiter.wait("missing", 0.05) is False
