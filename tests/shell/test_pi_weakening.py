"""新增静态跳过和恒假分支必须留下底线证据，不运行候选代码。"""

from pathlib import Path

import pytest

from tandem.core.level import bottom_line_reasons, compute_level
from tandem.core.model import Level
from tandem.shell.config import load_policy
from tandem.shell.diff_source import GitDiffSource
from tandem.shell.serde import changes_from_dict, changes_to_dict
from tests.shell.test_diff_source import _commit_file, _make_repo

BASE = "def test_a():\n    assert False\n"


@pytest.mark.parametrize(
    "after",
    [
        "import pytest\ndef test_a():\n    pytest.skip('later')\n    assert False\n",
        "import pytest\n@pytest.mark.skip\ndef test_a():\n    assert False\n",
        "import pytest\n@pytest.mark.skipif(False, reason='later')\n"
        "def test_a():\n    assert False\n",
        "import pytest\n@pytest.mark.xfail\ndef test_a():\n    assert False\n",
        "import pytest\ndef test_a():\n    pytest.xfail('later')\n    assert False\n",
        "import pytest\npytest.importorskip('missing')\ndef test_a():\n    assert False\n",
        "from pytest import skip as later\ndef test_a():\n    later('later')\n    assert False\n",
        "import pytest\npytestmark = pytest.mark.skip\ndef test_a():\n    assert False\n",
        "def test_a():\n    if False:\n        assert False\n",
        "def test_a():\n    if 0:\n        assert False\n",
        "def test_a():\n    if 1 == 2:\n        assert False\n",
        "def test_a():\n    if not True:\n        assert False\n",
        "def test_a():\n    if False and dynamic():\n        assert False\n",
        "def test_a():\n    while False:\n        assert False\n",
    ],
)
def test_new_static_weakening_is_d(tmp_path: Path, after: str) -> None:
    root = _make_repo(tmp_path)
    _commit_file(root, "tests/test_a.py", BASE, "test")
    _commit_file(root, "tests/test_a.py", after, "weaken")
    changes = GitDiffSource(cwd=root).collect("HEAD~1", "HEAD").changes
    assert changes.assertions_before == changes.assertions_after == 1
    assert compute_level(changes, load_policy()) is Level.D
    assert any("弱化" in reason for reason in bottom_line_reasons(changes, load_policy()))
    assert changes_from_dict(changes_to_dict(changes)) == changes


def test_existing_marker_is_not_reported_again(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    code = "import pytest\n@pytest.mark.skip\ndef test_a():\n    assert False\n"
    _commit_file(root, "tests/test_a.py", code, "existing marker")
    _commit_file(root, "tests/test_a.py", "\n" + code, "move line numbers")
    changes = GitDiffSource(cwd=root).collect("HEAD~1", "HEAD").changes
    assert changes.test_weakenings == ()
    assert compute_level(changes, load_policy()) is Level.C
