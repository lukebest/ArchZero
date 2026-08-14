"""Shared plugin registry: one raise-on-typo mechanism for every backend kind."""

from __future__ import annotations

import pytest

from archzero.evolve.registry import UnknownEvolveBackend, resolve_evolve_backend
from archzero.plugins import PluginRegistry, UnknownPlugin
from archzero.rtl.backend import get_rtl_backend
from archzero.rtl.registry import UnknownRtlBackend, registered_rtl_backends
from archzero.sign.backend import get_sign_backend
from archzero.sign.registry import UnknownSignBackend, registered_sign_backends


def test_plugin_registry_raises_on_unknown():
    reg: PluginRegistry = PluginRegistry("toy", "archzero.none", "fix the name")
    reg.register("alpha", lambda: "a")
    assert reg.names() == ("alpha",)
    assert reg.resolve("alpha")() == "a"
    with pytest.raises(UnknownPlugin, match="beta"):
        reg.resolve("beta")


def test_rtl_unknown_name_raises_instead_of_becoming_null(tmp_cfg):
    tmp_cfg.rtl.backend = "pycircut"
    with pytest.raises(UnknownRtlBackend, match="pycircut"):
        get_rtl_backend(tmp_cfg)


def test_rtl_missing_toolchain_is_null_not_an_error(tmp_cfg):
    tmp_cfg.rtl.backend = "pycircuit"
    tmp_cfg.rtl.pycircuit_root = str(tmp_cfg.state_dir / "missing_pyc")
    be = get_rtl_backend(tmp_cfg)
    assert be.name == "null"
    assert "pycircuit" in registered_rtl_backends()


def test_sign_disabled_stays_null_even_if_name_is_wrong(tmp_cfg):
    tmp_cfg.sign.enabled = False
    tmp_cfg.sign.backend = "openraod"
    assert get_sign_backend(tmp_cfg).name == "null"


def test_sign_enabled_unknown_name_raises(tmp_cfg):
    tmp_cfg.sign.enabled = True
    tmp_cfg.sign.backend = "openraod"
    with pytest.raises(UnknownSignBackend, match="openraod"):
        get_sign_backend(tmp_cfg)
    assert "null" in registered_sign_backends()


def test_evolve_typo_raises_instead_of_becoming_mapelites(tmp_cfg):
    tmp_cfg.evolve.backend = "mapelite"
    with pytest.raises(UnknownEvolveBackend, match="mapelite"):
        resolve_evolve_backend(tmp_cfg)


def test_evolve_mapelites_resolves(tmp_cfg):
    tmp_cfg.evolve.backend = "mapelites"
    be = resolve_evolve_backend(tmp_cfg)
    assert be.name == "mapelites"
