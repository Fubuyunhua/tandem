"""JS 词法回归：正则和同名变量不能替代断言，除号不能吞掉真正的调用。"""

from pathlib import Path

import pytest

from tandem.core.level import compute_level
from tandem.core.model import Level
from tandem.shell.assertions import count_assertions
from tandem.shell.config import load_policy
from tandem.shell.diff_source import GitDiffSource
from tests.shell.test_diff_source import _commit_file, _make_repo


@pytest.mark.parametrize(
    "code, expected",
    [
        ("const pattern = /expect()/;", 0),
        (r"const pattern = /[/]expect()/g;", 0),
        ("if (ok) /expect()/.test(text);", 0),
        ("if (ok) {} /expect()/.test(text);", 0),
        ("function f() { return /assert()/; }", 0),
        ("const assert = 0;", 0),
        ("function assert(value) {}", 0),
        ("const obj = {assert() {}};", 0),
        ("console.assert(true);", 1),
        ("assert.equal(1, 1);", 1),
        ("const result = 8 / expect(2).toBe(2) / 2;", 1),
        ("const result = factory() / assert(true) / 2;", 1),
        ("const result = {value: 2} / expect(2) / 2;", 1),
    ],
)
def test_js_lexical_assertion_positions(code: str, expected: int) -> None:
    assert count_assertions(code, "tests/a.test.js") == expected


@pytest.mark.parametrize(
    "before, after",
    [
        ("expect(false).toBe(true);", "const pattern = /expect()/;"),
        ("assert(false);", "const assert = 0;"),
    ],
)
def test_js_fake_replacement_is_d(tmp_path: Path, before: str, after: str) -> None:
    root = _make_repo(tmp_path)
    _commit_file(root, "tests/a.test.js", before + "\n", "assertion")
    _commit_file(root, "tests/a.test.js", after + "\n", "fake replacement")
    changes = GitDiffSource(cwd=root).collect("HEAD~1", "HEAD").changes
    assert changes.assertions_before == 1 and changes.assertions_after == 0
    assert compute_level(changes, load_policy()) is Level.D
