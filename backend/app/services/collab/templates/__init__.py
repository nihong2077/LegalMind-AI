"""案件模板适配配置（T1.7）

把「案情模板 → 星型图可注入件」的映射从**代码业务分支**中解耦出来：每个 adapter
（目前仅 ``court``）在独立模块中以**纯函数 + 可注入工厂**的形式给出自己的
``scheduler`` / ``host_advisor`` / ``interaction_card`` / ``conclude_producer``，
由集成期按模板 ``adapter`` 组装进 ``build_collab_graph(...)``。

- 本包内**不含任何图结构或固定边**（A1「代码只做护栏」）；
- 新增模板 adapter 时只需增加一个模块并在本文件 re-export，无需改动 graph。
"""
from __future__ import annotations

from .court import (
    COURT_ADAPTER,
    COURT_CLERK,
    COURT_LITIGANTS,
    build_court_host_advisor,
    build_court_interaction_card,
    build_court_wiring,
    court_scheduler,
    make_court_conclude_producer,
    make_court_verdict_runner,
)

__all__ = [
    "COURT_ADAPTER",
    "COURT_CLERK",
    "COURT_LITIGANTS",
    "build_court_host_advisor",
    "build_court_interaction_card",
    "build_court_wiring",
    "court_scheduler",
    "make_court_conclude_producer",
    "make_court_verdict_runner",
]
