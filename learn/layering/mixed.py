"""写法 A：判断和执行混在一起。

能跑，也不难懂。但请试着回答：怎么测试"重试 2 次后找人"这条规则？
CI 结果是随机的，时间是真实的，每次调用还会"启动 AI""推送手机"。
"""
import world


def handle_ci_result(pr: int, level: str) -> None:
    ci_green = world.github_ci_status(pr)
    if ci_green:
        world.append_event({"type": "decision", "pr": pr, "action": "done"})
        return

    events = world.read_event_log()
    attempts = sum(1 for e in events if e["pr"] == pr and e["action"] == "retry")
    if attempts < 2:
        world.append_event({"type": "decision", "pr": pr, "action": "retry"})
        world.run_agent("opencode", f"修复 PR {pr} 的 CI")
        return

    world.append_event({"type": "decision", "pr": pr, "action": "ask_human"})
    card = {"title": f"PR {pr} 重试 {attempts} 次仍失败，需要你决定"}
    hour = world.now().hour
    if (hour >= 23 or hour < 8) and level != "D":
        world.queue_for_digest(card)
    else:
        world.push_card(card)


if __name__ == "__main__":
    for round_no in range(1, 5):
        print(f"第 {round_no} 轮")
        handle_ci_result(12, level="C")
