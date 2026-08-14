"""Evolution backend registry — typos no longer silently become MAP-Elites."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from archzero.plugins import PluginRegistry, UnknownPlugin

if TYPE_CHECKING:  # pragma: no cover
    from archzero.config import FactoryConfig
    from archzero.evolve.backend import EvolutionBackend

EvolveBackendFactory = Callable[["FactoryConfig"], "EvolutionBackend"]

_ENTRY_POINT_GROUP = "archzero.evolve_backends"
_REG: PluginRegistry[EvolveBackendFactory] = PluginRegistry(
    kind="evolve backend",
    entry_point_group=_ENTRY_POINT_GROUP,
    hint="Fix [evolve].backend in archzero.toml, or register a backend via the "
    f"{_ENTRY_POINT_GROUP!r} entry-point group.",
)


class UnknownEvolveBackend(UnknownPlugin):
    def __init__(self, name: str, known: tuple[str, ...]) -> None:
        super().__init__(
            "evolve backend",
            name,
            known,
            f"Fix [evolve].backend in archzero.toml, or register a backend via the "
            f"{_ENTRY_POINT_GROUP!r} entry-point group.",
        )


def register_evolve_backend(
    name: str, factory: EvolveBackendFactory, *, replace: bool = False
) -> None:
    _REG.register(name, factory, replace=replace)


def unregister_evolve_backend(name: str) -> None:
    _REG.unregister(name)


def registered_evolve_backends() -> tuple[str, ...]:
    return _REG.names()


def resolve_evolve_backend(cfg: FactoryConfig, name: str | None = None) -> EvolutionBackend:
    key = (name if name is not None else (cfg.evolve.backend or "mapelites")).strip().lower()
    factory = _REG.get(key)
    if factory is None:
        raise UnknownEvolveBackend(key, _REG.names())
    return factory(cfg)


def _register_builtins() -> None:
    def _mapelites(cfg: FactoryConfig) -> EvolutionBackend:
        from archzero.evolve.mapelites import MapElitesBackend

        return MapElitesBackend()

    def _openevolve(cfg: FactoryConfig) -> EvolutionBackend:
        from archzero.evolve.openevolve_adapter import OpenEvolveBackend

        return OpenEvolveBackend()

    for name, factory in (("mapelites", _mapelites), ("openevolve", _openevolve)):
        if _REG.get(name) is None:
            _REG.register(name, factory)


_register_builtins()
