"""提示中的参数必须能按当前平台的 shell 原样还原。"""

import shlex
from types import SimpleNamespace

import pytest

from tandem.shell import local_run


@pytest.mark.parametrize("value", ["", "two words", "O'Brien", "$HOME;$(cmd)`x`\n第二行"])
def test_powershell_quotes(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setattr(local_run, "sys", SimpleNamespace(platform="win32"))
    quoted = local_run._quote(value)
    assert quoted.startswith("'") and quoted.endswith("'")
    assert quoted[1:-1].replace("''", "'") == value


@pytest.mark.parametrize("value", ["", "two words", "O'Brien", "$HOME;$(cmd)`x`\n第二行"])
def test_posix_quotes(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setattr(local_run, "sys", SimpleNamespace(platform="linux"))
    assert shlex.split(local_run._quote(value)) == [value]
