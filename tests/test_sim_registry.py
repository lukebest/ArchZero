"""Simulation backend registry: no silent stub fallback, plugins can register."""

from __future__ import annotations

import pytest

from archzero.sim.backend import get_backend
from archzero.sim.registry import (
    UnknownSimBackend,
    backend_name_for_domain,
    register_backend,
    registered_backends,
    unregister_backend,
)


def test_builtins_are_registered():
    names = registered_backends()
    for required in ("stub", "directed", "champsim", "gem5", "noc", "dataflow", "wafer"):
        assert required in names


def test_unknown_backend_raises_instead_of_becoming_stub(tmp_cfg):
    tmp_cfg.sim.backend = "champsm"
    with pytest.raises(UnknownSimBackend, match="champsm"):
        get_backend(tmp_cfg)


def test_explicit_noc_backend_resolves(tmp_cfg):
    tmp_cfg.sim.backend = "noc"
    backend = get_backend(tmp_cfg)
    assert backend.name == "noc"
    assert backend.available()


def test_domain_routes_cache_backends_to_noc():
    resolved, reason = backend_name_for_domain("champsim", "noc")
    assert resolved == "noc"
    assert reason is not None
    resolved, reason = backend_name_for_domain("noc", "noc")
    assert resolved == "noc"
    assert reason is None
    resolved, reason = backend_name_for_domain("champsim", "cache")
    assert resolved == "champsim"
    assert reason is None
    resolved, reason = backend_name_for_domain("champsim", "dataflow")
    assert resolved == "dataflow"
    assert reason is not None
    resolved, reason = backend_name_for_domain("champsim", "wafer")
    assert resolved == "wafer"
    assert reason is not None


def test_plugin_can_register_and_unregister(tmp_cfg):
    from archzero.sim.stub import StubSimBackend

    register_backend("toy", lambda cfg: StubSimBackend(cfg), replace=True)
    try:
        assert "toy" in registered_backends()
        tmp_cfg.sim.backend = "toy"
        assert get_backend(tmp_cfg).name == "stub"
    finally:
        unregister_backend("toy")
    assert "toy" not in registered_backends()
