"""Mechanism family → problem domain mapping."""

from __future__ import annotations

from archzero.sim.families import champsim_hosts, family_domain, request_domain


def test_family_domain_noc_vs_cache():
    assert family_domain("noc_rg") == "noc"
    assert family_domain("prefetch") == "cache"


def test_champsim_hosts_only_cache():
    assert champsim_hosts("prefetch") is True
    assert champsim_hosts("noc_rg") is False


def test_request_domain_from_meta_and_family():
    assert request_domain({"domain": "noc"}) == "noc"
    assert request_domain({"family": "noc_rg"}) == "noc"

