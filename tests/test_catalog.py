import dataclasses
import json

import pytest

from archzero.config import FactoryConfig
from archzero.llm.catalog import ModelCatalog, _serialize_raw


@dataclasses.dataclass
class _Variant:
    display_name: str
    is_default: bool = True
    params: tuple = ()


@dataclasses.dataclass
class _SDKModel:
    id: str
    display_name: str
    description: str = ""
    parameters: tuple = ()
    variants: tuple = ()


def test_serialize_raw_nested_dataclasses():
    item = _SDKModel(
        id="grok-4.5",
        display_name="Cursor Grok 4.5",
        variants=(_Variant(display_name="Cursor Grok 4.5"),),
    )
    raw = _serialize_raw(item)
    assert raw is not None
    assert raw["id"] == "grok-4.5"
    assert raw["variants"][0]["display_name"] == "Cursor Grok 4.5"
    # Must be JSON-serializable (the previous failure mode).
    json.dumps(raw)


@pytest.mark.asyncio
async def test_list_models_caches_sdk_dataclass_shapes(tmp_path, monkeypatch):
    cfg = FactoryConfig(state_dir=tmp_path / "state")
    cfg.ensure_dirs()
    catalog = ModelCatalog(cfg)

    async def fake_fetch():
        from archzero.llm.catalog import ModelInfo

        item = _SDKModel(
            id="default",
            display_name="Auto",
            variants=(_Variant(display_name="Auto"),),
        )
        return [ModelInfo(id=item.id, raw=_serialize_raw(item))]

    monkeypatch.setattr(catalog, "_fetch_remote", fake_fetch)
    models = await catalog.list_models(refresh=True)
    assert models[0].id == "default"
    cached = json.loads(catalog._cache_path.read_text(encoding="utf-8"))
    assert cached[0]["raw"]["variants"][0]["display_name"] == "Auto"
