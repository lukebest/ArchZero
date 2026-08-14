"""Shared plugin registry for sim / RTL / signoff / evolution backends.

One mechanism everywhere: register a factory, resolve by name, raise on
typos instead of silently substituting a stub. Third-party packages can
add factories through an ``importlib.metadata`` entry-point group.
"""

from __future__ import annotations

from typing import Any, Callable, Generic, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


class UnknownPlugin(ValueError):
    """Configured plugin name is not registered."""

    def __init__(self, kind: str, name: str, known: tuple[str, ...], hint: str) -> None:
        super().__init__(
            f"unknown {kind} {name!r}; registered: {', '.join(known) or '(none)'}. {hint}"
        )
        self.kind = kind
        self.name = name
        self.known = known


class PluginRegistry(Generic[F]):
    def __init__(self, kind: str, entry_point_group: str, hint: str) -> None:
        self.kind = kind
        self.entry_point_group = entry_point_group
        self.hint = hint
        self._factories: dict[str, F] = {}
        self._entry_points_loaded = False

    def register(self, name: str, factory: F, *, replace: bool = False) -> None:
        key = name.strip().lower()
        if not key:
            raise ValueError(f"{self.kind} name must be non-empty")
        if key in self._factories and not replace:
            raise ValueError(f"{self.kind} {key!r} already registered; pass replace=True")
        self._factories[key] = factory

    def unregister(self, name: str) -> None:
        self._factories.pop(name.strip().lower(), None)

    def names(self) -> tuple[str, ...]:
        self.load_entry_points()
        return tuple(sorted(self._factories))

    def get(self, name: str) -> F | None:
        self.load_entry_points()
        return self._factories.get(name.strip().lower())

    def resolve(self, name: str) -> F:
        factory = self.get(name)
        if factory is None:
            raise UnknownPlugin(self.kind, name.strip().lower(), self.names(), self.hint)
        return factory

    def load_entry_points(self) -> None:
        if self._entry_points_loaded:
            return
        self._entry_points_loaded = True
        try:
            from importlib.metadata import entry_points
        except ImportError:  # pragma: no cover
            return
        try:
            eps = entry_points(group=self.entry_point_group)
        except Exception:  # noqa: BLE001
            return
        for ep in eps:
            key = ep.name.strip().lower()
            if key in self._factories:
                continue
            try:
                self._factories[key] = ep.load()
            except Exception:  # noqa: BLE001
                continue
