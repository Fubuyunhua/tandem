"""回执解析测试：有效和无效两种情况。"""

from __future__ import annotations

import pytest

from tandem.shell.receipt import ReceiptError, parse_receipt, render_receipt


def test_valid_receipt() -> None:
    text = render_receipt(
        "DONE：加了一个纯函数",
        {
            "task_id": "task-001",
            "attempt": 2,
            "sha": "abc123",
            "plan": "先写内核",
            "brief": {
                "what": "加了等级计算",
                "why": "任务书要求",
                "verify": "pytest",
                "rollback": "git revert",
                "learn": "底线为什么要先查",
                "level": "C",
            },
        },
    )
    receipt = parse_receipt(text)
    assert receipt.conclusion == "DONE：加了一个纯函数"
    assert receipt.task_id == "task-001"
    assert receipt.attempt == 2
    assert receipt.sha == "abc123"
    assert receipt.plan == "先写内核"
    assert receipt.brief is not None
    assert receipt.brief.what == "加了等级计算"
    # 这份回执没有 changes 字段，所以没有警告
    assert not hasattr(receipt, "changes")
    assert receipt.warnings == ()


def test_receipt_without_changes_is_valid() -> None:
    receipt = parse_receipt('DONE\n{"task_id": "t", "attempt": 1, "sha": "abc"}')
    assert receipt.warnings == ()
    assert receipt.brief is None


@pytest.mark.parametrize("missing", ["task_id", "attempt", "sha"])
def test_receipt_missing_required_field_is_invalid(missing: str) -> None:
    payload = {"task_id": "t", "attempt": 1, "sha": "abc"}
    del payload[missing]
    import json

    with pytest.raises(ReceiptError, match=missing):
        parse_receipt("DONE\n" + json.dumps(payload))


def test_receipt_without_json_is_invalid() -> None:
    with pytest.raises(ReceiptError):
        parse_receipt("DONE：没有附 JSON")


def test_receipt_with_bad_json_is_invalid() -> None:
    with pytest.raises(ReceiptError):
        parse_receipt("DONE\n{这不是 JSON}")


def test_receipt_without_conclusion_is_invalid() -> None:
    with pytest.raises(ReceiptError):
        parse_receipt('   \n{"task_id": "t", "attempt": 1, "sha": "abc"}')


def test_empty_receipt_is_invalid() -> None:
    with pytest.raises(ReceiptError):
        parse_receipt("")


def test_attempt_must_be_a_positive_integer() -> None:
    with pytest.raises(ReceiptError):
        parse_receipt('DONE\n{"task_id": "t", "attempt": 0, "sha": "abc"}')
    with pytest.raises(ReceiptError):
        parse_receipt('DONE\n{"task_id": "t", "attempt": "2", "sha": "abc"}')
    with pytest.raises(ReceiptError):
        parse_receipt('DONE\n{"task_id": "t", "attempt": true, "sha": "abc"}')


def test_blank_sha_is_invalid() -> None:
    with pytest.raises(ReceiptError):
        parse_receipt('DONE\n{"task_id": "t", "attempt": 1, "sha": "  "}')


def test_bad_changes_block_is_ignored_too() -> None:
    """连格式不对的 changes 也不报错：这个字段本来就不采用了。"""
    receipt = parse_receipt(
        'DONE\n{"task_id": "t", "attempt": 1, "sha": "abc", "changes": {"paths": "不是列表"}}'
    )
    assert receipt.warnings
