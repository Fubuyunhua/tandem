"""底线覆盖测试配置、迁移根目录、目录自身和大小写别名。"""

import pytest

from tandem.core.level import compute_level
from tandem.core.model import ChangeSet, Level
from tandem.shell.config import load_policy


@pytest.mark.parametrize(
    "path",
    [
        "pytest.ini",
        ".pytest.ini",
        "tox.ini",
        "setup.cfg",
        "conftest.py",
        "tests/conftest.py",
        "noxfile.py",
        ".coveragerc",
        "ruff.toml",
        "pyrightconfig.json",
        "migrations/001.sql",
        "migrations",
        "src/tandem/core",
        ".github",
        "scripts/gate",
        "src/TANDEM/CORE/level.py",
        "RISK.YML",
    ],
)
def test_sensitive_paths_always_d(path: str) -> None:
    assert compute_level(ChangeSet(paths=(path,)), load_policy(), Level.B) is Level.D
