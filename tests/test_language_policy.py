from archzero.generation.cleanroom import IDEATE_PERSONA
from archzero.generation.divergence import DIVERGE_PERSONA
from archzero.generation.plain import REWRITE_PERSONA
from archzero.llm.language import MECHANISM_STYLE, NATIVE_ZH_POLICY


def test_native_zh_policy_mentions_simplified_chinese():
    assert "简体中文" in NATIVE_ZH_POLICY
    assert "title" in NATIVE_ZH_POLICY or "机制" in NATIVE_ZH_POLICY


def test_mechanism_style_is_engineer_four_part():
    assert "工程师" in MECHANISM_STYLE
    assert "决策：" in MECHANISM_STYLE
    assert "状态：" in MECHANISM_STYLE
    assert "冲突：" in MECHANISM_STYLE
    assert "相对基线：" in MECHANISM_STYLE
    assert "瓦尔拉斯" in MECHANISM_STYLE
    assert "isomorphism" in MECHANISM_STYLE


def test_ideation_personas_require_four_part_mechanism():
    for text in (DIVERGE_PERSONA, IDEATE_PERSONA, REWRITE_PERSONA):
        assert "决策" in text
        assert "状态" in text
        assert "冲突" in text
        assert "相对基线" in text
