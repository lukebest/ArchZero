"""RTL backend registry — unknown names raise, missing tools fall back to null."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from archzero.plugins import PluginRegistry, UnknownPlugin

if TYPE_CHECKING:  # pragma: no cover
    from archzero.config import FactoryConfig
    from archzero.rtl.backend import RtlBackend

RtlBackendFactory = Callable[["FactoryConfig"], "RtlBackend"]

_ENTRY_POINT_GROUP = "archzero.rtl_backends"
_REG: PluginRegistry[RtlBackendFactory] = PluginRegistry(
    kind="rtl backend",
    entry_point_group=_ENTRY_POINT_GROUP,
    hint="Fix [rtl].backend in archzero.toml, or register a backend via the "
    f"{_ENTRY_POINT_GROUP!r} entry-point group.",
)


class UnknownRtlBackend(UnknownPlugin):
    def __init__(self, name: str, known: tuple[str, ...]) -> None:
        super().__init__(
            "rtl backend",
            name,
            known,
            f"Fix [rtl].backend in archzero.toml, or register a backend via the "
            f"{_ENTRY_POINT_GROUP!r} entry-point group.",
        )


def register_rtl_backend(
    name: str, factory: RtlBackendFactory, *, replace: bool = False
) -> None:
    _REG.register(name, factory, replace=replace)


def unregister_rtl_backend(name: str) -> None:
    _REG.unregister(name)


def registered_rtl_backends() -> tuple[str, ...]:
    return _REG.names()


def resolve_rtl_backend(cfg: FactoryConfig, name: str | None = None) -> RtlBackend:
    """Resolve by name. ``pycircuit`` with a missing toolchain becomes null.

    A typo such as ``pycircut`` raises — that is not the same as 'tool not
    installed', and silently returning NullRtlBackend hid the misconfiguration.
    """
    key = (name if name is not None else (cfg.rtl.backend or "pycircuit")).strip().lower()
    factory = _REG.get(key)
    if factory is None:
        raise UnknownRtlBackend(key, _REG.names())
    backend = factory(cfg)
    if key == "pycircuit" and not backend.available():
        from archzero.rtl.backend import NullRtlBackend

        return NullRtlBackend()
    return backend


def _register_builtins() -> None:
    def _null(cfg: FactoryConfig) -> RtlBackend:
        from archzero.rtl.backend import NullRtlBackend

        return NullRtlBackend()

    def _pycircuit(cfg: FactoryConfig) -> RtlBackend:
        from archzero.rtl.backend import PyCircuitBackend

        return PyCircuitBackend(cfg)

    for name, factory in (("null", _null), ("pycircuit", _pycircuit)):
        if _REG.get(name) is None:
            _REG.register(name, factory)


_register_builtins()
