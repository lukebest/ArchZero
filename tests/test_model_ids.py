from archzero.llm.model_ids import resolve_model_ref, to_model_selection


def test_resolve_cursor_grok_high_fast():
    sdk_id, params = resolve_model_ref("cursor-grok-4.6-high-fast")
    assert sdk_id == "grok-4.6"
    assert params == {"effort": "high", "fast": "true"}


def test_resolve_cursor_grok_4_5_alias():
    sdk_id, params = resolve_model_ref("cursor-grok-4.5-high-fast")
    assert sdk_id == "grok-4.5"
    assert params == {"effort": "high", "fast": "true"}


def test_resolve_plain_sdk_id_passthrough():
    sdk_id, params = resolve_model_ref("composer-2.5")
    assert sdk_id == "composer-2.5"
    assert params == {}


def test_to_model_selection_builds_sdk_object():
    sel = to_model_selection("cursor-grok-4.6-high-fast")
    assert sel.id == "grok-4.6"
    by_id = {p.id: p.value for p in sel.params}
    assert by_id == {"effort": "high", "fast": "true"}
