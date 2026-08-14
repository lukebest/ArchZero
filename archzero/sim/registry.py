"""Simulation backend registry — thin wrapper over :class:`PluginRegistry`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from archzero.plugins import PluginRegistry, UnknownPlugin

if TYPE_CHECKING:  # pragma: no cover
    from archzero.config import FactoryConfig
    from archzero.sim.backend import SimBackend

SimBackendFactory = Callable[["FactoryConfig"], "SimBackend"]

_ENTRY_POINT_GROUP = "archzero.sim_backends"
_REG: PluginRegistry[SimBackendFactory] = PluginRegistry(
    kind="sim backend",
    entry_point_group=_ENTRY_POINT_GROUP,
    hint="Fix [sim].backend in archzero.toml, or register a backend via the "
    f"{_ENTRY_POINT_GROUP!r} entry-point group.",
)


class UnknownSimBackend(UnknownPlugin):
    """Configured ``sim.backend`` is not registered."""

    def __init__(self, name: str, known: tuple[str, ...]) -> None:
        super().__init__(
            "sim backend",
            name,
            known,
            f"Fix [sim].backend in archzero.toml, or register a backend via the "
            f"{_ENTRY_POINT_GROUP!r} entry-point group.",
        )


def register_backend(
    name: str, factory: SimBackendFactory, *, replace: bool = False
) -> None:
    _REG.register(name, factory, replace=replace)


def unregister_backend(name: str) -> None:
    _REG.unregister(name)


def registered_backends() -> tuple[str, ...]:
    return _REG.names()


def is_registered(name: str) -> bool:
    return _REG.get(name) is not None


_CACHE_SHAPED: frozenset[str] = frozenset({"stub", "directed", "champsim", "gem5"})

_DOMAIN_BACKEND: dict[str, str] = {
    "noc": "noc",
    "dataflow": "dataflow",
    "wafer": "wafer",
}


def backend_name_for_domain(requested: str, domain: str) -> tuple[str, str | None]:
    """Return ``(resolved_name, override_reason_or_None)``."""
    key = (requested or "stub").strip().lower()
    target = _DOMAIN_BACKEND.get(domain)
    if target and key in _CACHE_SHAPED:
        return target, (
            f"domain={domain} routed {key} → {target} "
            f"(cache backends cannot measure this domain)"
        )
    return key, None


def resolve_backend(cfg: FactoryConfig, name: str | None = None) -> SimBackend:
    key = (name if name is not None else cfg.sim.backend or "stub").strip().lower()
    factory = _REG.get(key)
    if factory is None:
        raise UnknownSimBackend(key, _REG.names())
    return factory(cfg)


def resolve_backend_for_domain(
    cfg: FactoryConfig, domain: str, name: str | None = None
) -> tuple[SimBackend, str, str | None]:
    requested = name if name is not None else (cfg.sim.backend or "stub")
    resolved, reason = backend_name_for_domain(requested, domain)
    return resolve_backend(cfg, resolved), resolved, reason


def _register_builtins() -> None:
    def _stub(cfg: FactoryConfig) -> SimBackend:
        from archzero.sim.stub import StubSimBackend

        return StubSimBackend(cfg)

    def _directed(cfg: FactoryConfig) -> SimBackend:
        from archzero.sim.directed import DirectedSimBackend

        return DirectedSimBackend(cfg)

    def _champsim(cfg: FactoryConfig) -> SimBackend:
        from archzero.sim.champsim import ChampSimBackend

        return ChampSimBackend(cfg)

    def _gem5(cfg: FactoryConfig) -> SimBackend:
        from archzero.sim.gem5 import Gem5Backend

        return Gem5Backend(cfg)

    def _noc(cfg: FactoryConfig) -> SimBackend:
        from archzero.sim.noc import NocAnalyticBackend

        return NocAnalyticBackend(cfg)

    def _dataflow(cfg: FactoryConfig) -> SimBackend:
        from archzero.sim.dataflow import DataflowAnalyticBackend

        return DataflowAnalyticBackend(cfg)

    def _wafer(cfg: FactoryConfig) -> SimBackend:
        from archzero.sim.wafer import WaferAnalyticBackend

        return WaferAnalyticBackend(cfg)

    for name, factory in (
        ("stub", _stub),
        ("directed", _directed),
        ("champsim", _champsim),
        ("gem5", _gem5),
        ("noc", _noc),
        ("dataflow", _dataflow),
        ("wafer", _wafer),
    ):
        if _REG.get(name) is None:
            _REG.register(name, factory)


_register_builtins()
