"""写法 B 的内核：只做判断。

规则：这个文件不准 import 任何碰外部世界的模块（网络、文件、时间、随机数、进程）。
test_core.py 里有一个测试会检查这一点，相当于 CI 里的"边界守卫"。
所有需要的信息都由外壳作为参数传进来，所有结果都作为数据返回出去。
"""

MAX_RETRIES = 2
QUIET_START, QUIET_END = 23, 8  # 静默时段：23:00 至次日 08:00


def attempts_so_far(events: list[dict], pr: int) -> int:
    """从历史事件里数出这个 PR 已经重试了几次。"""
    return sum(1 for e in events if e["pr"] == pr and e["action"] == "retry")


def after_ci(ci_green: bool, attempts: int, pr: int) -> dict:
    """CI 跑完后下一步做什么：结束、重试，还是找人。"""
    if ci_green:
        return {"pr": pr, "action": "done", "why": "CI 已变绿"}
    if attempts < MAX_RETRIES:
        return {"pr": pr, "action": "retry", "why": f"CI 仍为红，已重试 {attempts} 次，未到上限"}
    return {
        "pr": pr,
        "action": "ask_human",
        "why": f"已重试 {attempts} 次仍失败",
        "card": {"title": f"PR {pr} 重试 {attempts} 次仍失败，需要你决定"},
    }


def should_push(hour: int, level: str) -> bool:
    """现在要不要推送到手机。静默时段只放行 D 级。"""
    quiet = hour >= QUIET_START or hour < QUIET_END
    return (not quiet) or level == "D"
