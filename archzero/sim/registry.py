"""Simulation backend registry.

Replaces a hardwired ``if name == ...`` chain in :mod:`archzero.sim.backend`.
Two things change beyond tidiness:

- **Third parties can add evaluators.** A separate package can ship a NoC,
  Timeloop, or wafer-fabric backend and register it through the
  ``archzero.sim_backends`` entry-point group without editing this repo.
- **Typos stop being silent.** The old factory fell through to the synthetic
  stub for any unrecognised name, so ``backend = "champsm"`` produced made-up
  numbers that looked like a real ChampSim run. Unknown names now raise.

Backends register lazily: the factory closure imports its module on first use,
so configuring ``stub`` never imports the heavier backends.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from archzero.config import FactoryConfig
    from archzero.sim.backend import SimBackend

SimBackendFactory = Callable[["FactoryConfig"], "SimBackend"]

_REGISTRY: dict[str, SimBackendFactory] = {}
_ENTRY_POINT_GROUP = "archzero.sim_backends"
_entry_points_loaded = False


class UnknownSimBackend(ValueError):
    """Configured ``sim.backend`` is not registered.

    Raised rather than falling back to the stub: silently substituting
    synthetic evidence for a mistyped backend name is the same class of bug as
    grading a NoC spec against cache thresholds.
    """

    def __init__(self, name: str, known: tuple[str, ...]) -> None:
        super().__init__(
            f"unknown sim backend {name!r}; registered: {', '.join(known) or '(none)'}. "
            f"Fix [sim].backend in archzero.toml, or register a backend via the "
            f"{_ENTRY_POINT_GROUP!r} entry-point group."
        )
        self.name = name
        self.known = known


def register_backend(
    name: str, factory: SimBackendFactory, *, replace: bool = False
) -> None:
    """Register a backend factory under ``name``.

    Set ``replace`` to override an existing entry; without it a duplicate name
    raises, so two plugins cannot quietly shadow each other.
    """
    key = name.strip().lower()
    if not key:
        raise ValueError("backend name must be non-empty")
    if key in _REGISTRY and not replace:
        raise ValueError(f"sim backend {key!r} already registered; pass replace=True")
    _REGISTRY[key] = factory


def unregister_backend(name: str) -> None:
    """Remove a backend. Mainly for tests and plugin teardown."""
    _REGISTRY.pop(name.strip().lower(), None)


def registered_backends() -> tuple[str, ...]:
    _load_entry_points()
    return tuple(sorted(_REGISTRY))


def is_registered(name: str) -> bool:
    _load_entry_points()
    return name.strip().lower() in _REGISTRY


# Cache-shaped backends cannot produce NoC quantities. When the problem
# package is an interconnect study and the configured backend is one of
# these, we route to the analytic NoC model rather than inventing MPKI.
_CACHE_SHAPED: frozenset[str] = frozenset({"stub", "directed", "champsim", "gem5"})


def backend_name_for_domain(requested: str, domain: str) -> tuple[str, str | None]:
    """Return ``(resolved_name, override_reason_or_None)``."""
    key = (requested or "stub").strip().lower()
    if domain == "noc" and key in _CACHE_SHAPED:
        return "noc", f"domain=noc routed {key} → noc (cache backends cannot measure tail latency)"
    return key, None


def resolve_backend(cfg: FactoryConfig, name: str | None = None) -> SimBackend:
    """Build the backend named by ``name`` (default: ``cfg.sim.backend``)."""
    _load_entry_points()
    key = (name if name is not None else cfg.sim.backend or "stub").strip().lower()
    factory = _REGISTRY.get(key)
    if factory is None:
        raise UnknownSimBackend(key, tuple(sorted(_REGISTRY)))
    return factory(cfg)


def resolve_backend_for_domain(
    cfg: FactoryConfig, domain: str, name: str | None = None
) -> tuple[SimBackend, str, str | None]:
    """Resolve, rerouting cache-shaped backends when the spec is not a cache problem."""
    requested = name if name is not None else (cfg.sim.backend or "stub")
    resolved, reason = backend_name_for_domain(requested, domain)
    return resolve_backend(cfg, resolved), resolved, reason


def _load_entry_points() -> None:
    """Discover third-party backends once, tolerating a broken plugin."""
    global _entry_points_loaded
    if _entry_points_loaded:
        return
    _entry_points_loaded = True
    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover - stdlib
        return
    try:
        eps = entry_points(group=_ENTRY_POINT_GROUP)
    except Exception:  # noqa: BLE001 - a bad plugin must not break the core
        return
    for ep in eps:
        if ep.name.strip().lower() in _REGISTRY:
            continue
        try:
            loaded = ep.load()
        except Exception:  # noqa: BLE001
            continue
        _REGISTRY[ep.name.strip().lower()] = loaded


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

    for name, factory in (
        ("stub", _stub),
        ("directed", _directed),
        ("champsim", _champsim),
        ("gem5", _gem5),
        ("noc", _noc),
    ):
        _REGISTRY.setdefault(name, factory)


_register_builtins()
