"""CognitiveOS 使用的路径。

所有内容都根在单个 ``root`` 目录之下，所以项目可以放在磁盘上任何
位置。默认是当前工作目录。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    """CognitiveOS 关心的所有目录的合集。

    把它们集中到一处，测试时方便覆盖 ``root``，bootstrap 末尾也方便
    打一张清晰的状态面板。
    """

    root: Path

    @classmethod
    def default(cls) -> "Paths":
        return cls(root=Path.cwd().resolve())

    # --- 顶层布局 ---------------------------------------------------

    @property
    def knowledge(self) -> Path:
        return self.root / "knowledge"

    @property
    def sources(self) -> Path:
        return self.knowledge / "sources"

    @property
    def normalized(self) -> Path:
        return self.knowledge / "normalized"

    @property
    def wiki(self) -> Path:
        return self.knowledge / "wiki"

    @property
    def dashboard(self) -> Path:
        # 旧目录——留着只是为了兼容老脚本。新仪表盘写在项目根的
        # ``index.html``。
        return self.root / "dashboard"

    @property
    def dashboard_index(self) -> Path:
        # CognitiveOS UI 的唯一真源在项目根，这样 ``file://`` 链接
        # ``knowledge/`` 时不需要额外做路径运算。
        return self.root / "index.html"

    @property
    def cache(self) -> Path:
        return self.root / ".cogos"

    @property
    def config_file(self) -> Path:
        return self.root / "cogos.yaml"

    # --- 辅助 ------------------------------------------------------------

    def ensure(self) -> None:
        """创建 CognitiveOS 写过的所有目录。"""
        for p in (
            self.knowledge,
            self.sources,
            self.normalized,
            self.wiki,
            # dashboard/ 不再需要——index.html 写在根。
            self.cache,
        ):
            p.mkdir(parents=True, exist_ok=True)