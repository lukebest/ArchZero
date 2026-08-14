"""Signoff backend registry — unknown names raise instead of becoming null."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from archzero.plugins import PluginRegistry, UnknownPlugin

if TYPE_CHECKING:  # pragma: no cover
    from archzero.config import FactoryConfig
    from archzero.sign.backend import SignBackend

SignBackendFactory = Callable[["FactoryConfig"], "SignBackend"]

_ENTRY_POINT_GROUP = "archzero.sign_backends"
_REG: PluginRegistry[SignBackendFactory] = PluginRegistry(
    kind="sign backend",
    entry_point_group=_ENTRY_POINT_GROUP,
    hint="Fix [sign].backend in archzero.toml, or register a backend via the "
    f"{_ENTRY_POINT_GROUP!r} entry-point group.",
)


class UnknownSignBackend(UnknownPlugin):
    def __init__(self, name: str, known: tuple[str, ...]) -> None:
        super().__init__(
            "sign backend",
            name,
            known,
            f"Fix [sign].backend in archzero.toml, or register a backend via the "
            f"{_ENTRY_POINT_GROUP!r} entry-point group.",
        )


def register_sign_backend(
    name: str, factory: SignBackendFactory, *, replace: bool = False
) -> None:
    _REG.register(name, factory, replace=replace)


def unregister_sign_backend(name: str) -> None:
    _REG.unregister(name)


def registered_sign_backends() -> tuple[str, ...]:
    return _REG.names()


def resolve_sign_backend(cfg: FactoryConfig, name: str | None = None) -> SignBackend:
    if not cfg.sign.enabled:
        from archzero.sign.backend import NullSignBackend

        return NullSignBackend()
    key = (name if name is not None else (cfg.sign.backend or "null")).strip().lower()
    factory = _REG.get(key)
    if factory is None:
        raise UnknownSignBackend(key, _REG.names())
    return factory(cfg)


def _register_builtins() -> None:
    def _null(cfg: FactoryConfig) -> SignBackend:
        from archzero.sign.backend import NullSignBackend

        return NullSignBackend()

    if _REG.get("null") is None:
        _REG.register("null", _null)


_register_builtins()
