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
