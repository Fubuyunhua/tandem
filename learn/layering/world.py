"""模拟的"外部世界"：网络、手机、日志存储、时钟、随机。

真实系统里，这些是 GitHub、飞书、数据库和启动 AI 进程。这里用打印和随机数来模拟，
目的只有一个：让你看到它们的共同点——结果不可控，或者会改变外部世界。
"""
import random
from datetime import datetime

_event_log: list[dict] = []  # 模拟只追加的事件日志


def github_ci_status(pr: int) -> bool:
    green = random.random() < 0.4
    print(f"  [网络] 查询 PR {pr} 的 CI 状态 → {'绿' if green else '红'}")
    return green


def read_event_log() -> list[dict]:
    print(f"  [存储] 读取事件日志（共 {len(_event_log)} 条）")
    return list(_event_log)


def append_event(event: dict) -> None:
    _event_log.append(event)
    print(f"  [存储] 写入日志：{event}")


def run_agent(agent: str, task: str) -> None:
    print(f"  [进程] 启动 {agent}：{task}")


def push_card(card: dict) -> None:
    print(f"  [手机] 推送卡片：{card['title']}")


def queue_for_digest(card: dict) -> None:
    print(f"  [存储] 静默时段，卡片放进明早摘要：{card['title']}")


def now() -> datetime:
    return datetime.now()
