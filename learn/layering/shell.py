"""写法 B 的外壳：只做执行。

每一步都是同一个套路：从外部世界取数据 → 交给内核判断 → 按决定执行 → 记日志。
这里没有任何 if 在做"业务判断"，只有"按决定分派动作"。
"""
import core
import world


def handle_ci_result(pr: int, level: str) -> None:
    # 1. 取数据
    ci_green = world.github_ci_status(pr)
    events = world.read_event_log()
    hour = world.now().hour

    # 2. 问内核
    decision = core.after_ci(ci_green, core.attempts_so_far(events, pr), pr)

    # 3. 记日志，再执行
    world.append_event({k: v for k, v in decision.items() if k != "card"})
    if decision["action"] == "retry":
        world.run_agent("opencode", f"修复 PR {pr} 的 CI")
    elif decision["action"] == "ask_human":
        if core.should_push(hour, level):
            world.push_card(decision["card"])
        else:
            world.queue_for_digest(decision["card"])


if __name__ == "__main__":
    for round_no in range(1, 5):
        print(f"第 {round_no} 轮")
        handle_ci_result(12, level="C")
