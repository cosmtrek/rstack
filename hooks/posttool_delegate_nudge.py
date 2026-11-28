#!/usr/bin/env python3
"""PostToolUse：主会话连续只读调用达到阈值时注入一次「委派提醒」，不拦截。
只指向全局委派约定，不点名执行方。派发（Bash 真正执行 dispatch.sh，cat / 读它不算）或写操作（改文件、git commit/push）清零。
出错一律静默放行。--selftest 用临时状态目录跑一遍，期望在第 N 次输出提醒。"""
import json, os, re, sys, time

THRESHOLD = int(os.environ.get("NUDGE_THRESHOLD", "25"))
WRITE = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
SKIP = {"Skill", "ToolSearch", "AskUserQuestion", "TodoWrite"}  # 不算读也不清零的元操作，按你的工具集补
RSTACK_HOME = os.path.expanduser(os.environ.get("RSTACK_HOME") or "~/.rstack")
STATE = os.path.expanduser(os.environ.get("NUDGE_STATE") or os.path.join(RSTACK_HOME, "state", "hooks", "nudge"))
LOG = os.path.join(RSTACK_HOME, "state", "hooks", "hits.jsonl")
# dispatch.sh 出现在命令执行位置才算派发：行首或 ; & | ( 之后，可带 VAR=值 / env / timeout N / bash / sh / exec / nohup 前缀，
# 路径可加引号（"$DG/dispatch.sh"）。cat / sed / grep 等把它当参数的不算。
DISPATCH = re.compile(
    r"""(?:^|[;&|(])\s*(?:(?:env\s+)?(?:[A-Za-z_]\w*=(?:"[^"]*"|'[^']*'|[^\s;&|]*)\s+)*)"""
    r"""(?:(?:timeout\s+\S+|bash|sh|exec|nohup|time)\s+)*["']?[^\s;&|"'<>]*dispatch\.sh["']?(?=$|[\s;&|)])""", re.M)
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1.*?\n.*?^\s*\2\s*$", re.S | re.M)


def is_dispatch(cmd):
    """命令里是否真的执行了 dispatch.sh（heredoc 正文不算）。timing.py 复用它。"""
    return isinstance(cmd, str) and bool(DISPATCH.search(HEREDOC.sub("<<HEREDOC", cmd)))


MSG = ("[委派提醒] 本会话从上次派发或写操作以来已连续 {n} 次只读调用。"
       "按全局约定「读得多、改得多的活派出去」重新判断一次：剩下的取证还要读很多，就按约定的委派方式派出去；"
       "几步内能收尾就继续。不用回复这条提醒。")


def kind(name, inp):
    s = json.dumps(inp, ensure_ascii=False)
    if name == "Bash" and is_dispatch(inp.get("command")):  # 派发了（claude-lead 的 dispatch 脚本），清零
        return "reset"
    if name in WRITE or re.search(r"\bgit\s+(commit|push)\b", s):
        return "reset"
    if name in SKIP:
        return "skip"
    return "read"


def main(selftest=False):
    d = json.load(sys.stdin)
    if d.get("agent_id"):  # 子代理不提醒
        return
    sid = re.sub(r"[^\w-]", "", d.get("session_id") or "")
    if not sid:
        return
    k = kind(d.get("tool_name", ""), d.get("tool_input") or {})
    if k == "skip":
        return
    os.umask(0o077)
    os.makedirs(STATE, exist_ok=True)
    path = os.path.join(STATE, sid)
    try:
        n = int(open(path).read() or 0)
    except (OSError, ValueError):
        n = 0
    n = 0 if k == "reset" else n + 1
    with open(path, "w") as f:
        f.write(str(n))
    if n and n % THRESHOLD == 0:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                 "additionalContext": MSG.format(n=n)}}, ensure_ascii=False))
        if not selftest:
            os.makedirs(os.path.dirname(LOG), exist_ok=True)
            with open(LOG, "a") as f:
                f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "rule": "delegate-nudge",
                                    "decision": "context", "session": sid, "count": n}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    try:
        main(selftest="--selftest" in sys.argv)
    except Exception:
        pass
    sys.exit(0)
