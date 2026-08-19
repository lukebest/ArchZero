"""Output language policy for researcher-facing ArchZero content."""

from __future__ import annotations

NATIVE_ZH_POLICY = """\
【语言要求 / Language — 必须遵守】
面向研究员阅读的自然语言内容，必须原生使用简体中文撰写（不要先写英文再翻译）。
包括但不限于：title、机制/方案描述、rationale、summary、expected_effect、risks、
novelty_notes、评审意见、报告段落、DECISION 说明。
以下保持英文：JSON 字段名、代码、文件路径、条款 ID（如 REQ-001）、family 短标识、
模型 id、API/CLI 标志。
"""

MECHANISM_STYLE = """\
【机制写法 — 必须遵守】
读者是做芯片 / 互连 / 缓存的工程师。title 和 mechanism 必须能直接画进状态机。
title：像论文小节标题，用硬件名词（节点、平面、方向、注入口、预约表、重试、flit）。
禁止把跨学科专名当标题主体（瓦尔拉斯、函子、奈奎斯特、斯坦克尔伯格、感知掩蔽、范畴）。
mechanism 固定四段，每段一两句，分别以「决策：」「状态：」「冲突：」「相对基线：」开头：
1) 决策：改的是选面、选向、何时注入，还是冲突谁赢
2) 状态：每个节点存什么（表、计数器、位宽、谁写）
3) 冲突：口忙或两包相撞时的确定性动作（停、换向、换面、推迟一拍）
4) 相对基线：相对「随机选面 + 最短路方向」只多了哪一条规则
跨域类比只写在 isomorphism；mechanism 里用硬件语言复述，不要用源领域术语讲故事。
"""
