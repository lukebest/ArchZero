from archzero.llm.language import NATIVE_ZH_POLICY


def test_native_zh_policy_mentions_simplified_chinese():
    assert "简体中文" in NATIVE_ZH_POLICY
    assert "title" in NATIVE_ZH_POLICY or "机制" in NATIVE_ZH_POLICY
