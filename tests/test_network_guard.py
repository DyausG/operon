"""The conftest network guard still blocks real connections; only socketpair's own loopback
self-connection (the Windows fallback asyncio needs for its event loop) is exempt."""
from __future__ import annotations
import socket

import pytest


def _listener() -> socket.socket:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    return srv


def test_loopback_connect_is_still_blocked():
    srv = _listener()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            with pytest.raises(AssertionError, match="network access is blocked"):
                s.connect(srv.getsockname())
            with pytest.raises(AssertionError, match="network access is blocked"):
                s.connect_ex(srv.getsockname())
    finally:
        srv.close()


def test_remote_connect_and_dns_are_still_blocked():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        with pytest.raises(AssertionError, match="network access is blocked"):
            s.connect(("93.184.216.34", 80))
    with pytest.raises(AssertionError, match="DNS/network access is blocked"):
        socket.getaddrinfo("example.com", 443)


def test_socketpair_works_and_does_not_leave_the_exemption_open():
    a, b = socket.socketpair()
    try:
        a.sendall(b"ping")
        assert b.recv(4) == b"ping"
    finally:
        a.close()
        b.close()
    srv = _listener()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            with pytest.raises(AssertionError, match="network access is blocked"):
                s.connect(srv.getsockname())
    finally:
        srv.close()


def test_remote_ipv6_connect_is_still_blocked():
    if not socket.has_ipv6:
        pytest.skip("no IPv6 support")
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
        with pytest.raises(AssertionError, match="network access is blocked"):
            s.connect(("2606:2800:220:1:248:1893:25c7:1946", 80, 0, 0))


def test_the_exemption_is_scoped_to_the_thread_inside_socketpair():
    """Another thread creating socketpairs never opens a window for this thread's connects."""
    import threading

    stop = threading.Event()

    def churn():
        while not stop.is_set():
            a, b = socket.socketpair()
            a.close()
            b.close()

    worker = threading.Thread(target=churn, daemon=True)
    worker.start()
    srv = _listener()
    try:
        for _ in range(200):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                with pytest.raises(AssertionError, match="network access is blocked"):
                    s.connect(srv.getsockname())
    finally:
        stop.set()
        worker.join(5)
        srv.close()


def test_event_loops_start_under_the_guard():
    import asyncio

    async def answer():
        return 42

    assert asyncio.run(answer()) == 42
