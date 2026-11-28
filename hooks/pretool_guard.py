#!/usr/bin/env python3
"""Claude Code PreToolUse(Bash) 守卫：命中已知的高代价误操作时拦下或要求确认，并带上修复提示。

规则（见同目录 README.md）：
- 默认 decision=ask；只有「一定会失败」的操作才 deny。
- 匹配写窄；命令里带 `# confirmed-by-user` 视为用户已确认，直接放行（仍记日志）。
- 出错就放行：任何异常都 exit 0，不影响正常命令。
- 每次命中写一行到 $RSTACK_HOME/state/hooks/hits.jsonl（RSTACK_HOME 默认 ~/.rstack），供 weekly-retro 统计命中率和误拦率。
- 规则来源：$RSTACK_RULES 指定的 JSON 文件，否则 $RSTACK_HOME/config/guard_rules.json；都没有（或读不了）就用下面的内置示例。
  环境相关的规则只写进私有文件，不进公开仓库。格式见 guard_rules.example.json。
- `--selftests`：逐行打印当前生效规则的 selftest 命令，供 weekly-retro 每期自测。
"""
import json, os, re, sys, time

RSTACK_HOME = os.path.expanduser(os.environ.get("RSTACK_HOME") or "~/.rstack")

# 每条规则来自一次复盘：某个命令「一定会失败」或「代价高到必须先问」。下面两条是内置示例；
# 你自己复盘出来的规则写进 $RSTACK_HOME/config/guard_rules.json（私有，不进仓库），有它就不用这里的示例。
EXAMPLE_RULES = [
    {
        "id": "force-push-main",
        # 强推主干：一定是高代价操作，但偶尔确实要做，所以 ask 而不是 deny
        "pattern": r"git\s+push\b(?=[^\n;&|]*(?:--force\b|--force-with-lease\b|\s-f\b))(?=[^\n;&|]*(?<![\w./-])(?:main|master)(?![\w./-]))",
        "decision": "ask",
        "reason": "要强推 main / master，会覆盖远端别人的提交。先 git fetch 看远端比本地多了哪些提交；"
                  "确认要覆盖，在命令末尾加 `# confirmed-by-user` 重跑。",
        # weekly-retro 每期用 Bash 工具跑一次，期望被拦且写日志；false 短路，hook 失效也不会真执行
        "selftest": "false && git push --force origin main  # retro-selftest",
    },
    {
        "id": "prod-config-cli",
        # 示例：某个配置中心的 prod 环境只能在网页上改，CLI 一定被拒，所以 deny 并给出正确做法
        "pattern": r"mycli\s+config\s+(?:create|update)\b(?=[^\n;&|]*--env[ =]prod\b)",
        "decision": "deny",
        "reason": "prod 配置用 CLI 改一定会被审批管控拒绝。把要改的 key、值、说明整理成表交给用户在网页上改。"
                  "如果用户明确说管控已放开，在命令末尾加 `# confirmed-by-user` 重跑。",
        "selftest": "false && mycli config update app.key --env prod  # retro-selftest",
    },
]
OVERRIDE = "# confirmed-by-user"
# 只在命令执行位置匹配：行首、;、&&、||、|、( 之后，可带 timeout / env 前缀
CMD_POS = r"(?:^|[;&|(]|\btimeout\s+\S+\s+|\benv\s+(?:\S+=\S+\s+)*)\s*"
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1.*?\n.*?^\s*\2\s*$", re.S | re.M)

def executable_text(cmd):
    # 去掉 heredoc 正文，避免「写文件的内容里出现命令文本」被误拦
    return HEREDOC.sub("<<HEREDOC", cmd)
LOG = os.path.join(RSTACK_HOME, "state", "hooks", "hits.jsonl")


def load_rules():
    """私有规则文件优先：顶层是规则列表，或 {"rules": [...]}。读不了、格式不对就回退内置示例；单条规则坏了只跳过那一条。"""
    path = os.environ.get("RSTACK_RULES") or os.path.join(RSTACK_HOME, "config", "guard_rules.json")
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return EXAMPLE_RULES
    rules = data.get("rules") if isinstance(data, dict) else data
    if not isinstance(rules, list):
        return EXAMPLE_RULES
    ok = []
    for r in rules:
        try:
            re.compile(r["pattern"])
            if r["decision"] in ("ask", "deny") and r["id"] and r["reason"]:
                ok.append(r)
        except Exception:
            continue
    return ok

def log(entry):
    try:
        os.umask(0o077)
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

def main():
    if "--selftests" in sys.argv[1:]:
        for r in load_rules():
            if r.get("selftest"):
                print(r["selftest"])
        return
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Bash":
        return
    cmd = (data.get("tool_input") or {}).get("command", "")
    text = executable_text(cmd)
    for r in load_rules():
        if not re.search(CMD_POS + r["pattern"], text, re.M):
            continue
        overridden = OVERRIDE in cmd
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "rule": r["id"],
             "decision": "allow-override" if overridden else r["decision"],
             "session": data.get("session_id"), "selftest": "# retro-selftest" in cmd})
        if overridden:
            return
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": r["decision"],
            "permissionDecisionReason": f"[{r['id']}] {r['reason']}"}}, ensure_ascii=False))
        return

if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
