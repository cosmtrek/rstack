#!/usr/bin/env python3
"""Claude Code Stop hook：本回合改了界面文件，却在最后一次改动之后没看过真实界面，就拦一次收尾。

- 「给用户看过」= 最后一段回复里嵌了图片，或最后一次界面改动之后调用过会展示给用户的工具（默认 html_render）。
  agent 自己的预览快照用户看不到，不算。
- 「改了界面」= 本回合用 Edit/Write 或 Bash 写过匹配 ui_paths 的文件；或 cwd 所在仓库里有匹配 ui_paths 的未提交文件
  修改时间晚于本回合开始（覆盖派给别的 agent 改的情况）。
- 只拦一次：stop_hook_active 为真时放行，避免死循环；回复里写 `[no-screenshot: 原因]` 视为豁免（记日志）。
- 配置（可选）：$RSTACK_HOME/config/ui_check.json，键 ui_paths / evidence_tools（正则）、message（提示语）。
- 出错放行；命中写 $RSTACK_HOME/state/hooks/hits.jsonl（rule=ui-evidence）。
- `--selftest`：用内置的假 transcript 自测，期望输出 block 并记为 ui-evidence:selftest。
"""
import datetime, json, os, re, subprocess, sys, tempfile, time

RSTACK_HOME = os.path.expanduser(os.environ.get("RSTACK_HOME") or "~/.rstack")
DEFAULTS = {
    "ui_paths": r"\.(?:tsx|jsx|vue|svelte|css|scss)$",
    "evidence_tools": r"html_render",
    "message": "本回合改了界面文件，但最后一次改动之后还没在真实界面里看过。收尾前：截图并嵌进回复；"
               "对照最接近的现有界面自检一遍，在回复里写明参照的是哪个界面。确实不需要（纯逻辑、没有可见变化）"
               "就在回复里写 `[no-screenshot: 原因]`。",
}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
BASH_WRITE = re.compile(r"sed\s+-i|>\s*\S|python3?\s+-|tee\s|apply_patch|perl\s+-pi")


def config():
    cfg = dict(DEFAULTS)
    try:
        with open(os.path.join(RSTACK_HOME, "config", "ui_check.json"), encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def log(decision, session, selftest=False):
    try:
        d = os.path.join(RSTACK_HOME, "state", "hooks")
        os.makedirs(d, exist_ok=True)
        rule = "ui-evidence:selftest" if selftest else "ui-evidence"
        with open(os.path.join(d, "hits.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "rule": rule, "decision": decision,
                                "session": session, "selftest": selftest}) + "\n")
    except OSError:
        pass


def is_real_user(d):
    if d.get("type") != "user" or d.get("isSidechain") or d.get("isMeta"):
        return False
    c = d.get("message", {}).get("content")
    if isinstance(c, str):
        return not c.startswith("<")
    return isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "text" for b in c)


def changed_since(cwd, since, ui):
    if not cwd or not since:
        return False
    try:
        out = subprocess.run(["git", "-C", cwd, "status", "--porcelain", "-uall"], capture_output=True, text=True,
                             timeout=3).stdout
        top = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                             timeout=3).stdout.strip()
        t0 = datetime.datetime.fromisoformat(since.replace("Z", "+00:00")).timestamp()
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    for line in out.splitlines():
        path = os.path.join(top, line[3:].split(" -> ")[-1])
        if ui.search(path) and os.path.exists(path) and os.path.getmtime(path) > t0:
            return True
    return False


def verdict(transcript, cfg, cwd=None):
    ui, ev = re.compile(cfg["ui_paths"]), re.compile(cfg["evidence_tools"], re.I)
    recs = []
    with open(transcript, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                recs.append(json.loads(line))
            except ValueError:
                continue
    start = max((i for i, d in enumerate(recs) if is_real_user(d)), default=-1)
    last_edit = last_evidence = -1
    since = recs[start].get("timestamp") if start >= 0 else None
    final_text = ""
    for i, d in enumerate(recs[start + 1:], start + 1):
        if d.get("type") != "assistant" or d.get("isSidechain"):
            continue
        for b in d.get("message", {}).get("content", []):
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and b.get("text", "").strip():
                final_text = b["text"]
            if b.get("type") != "tool_use":
                continue
            name, inp = b.get("name", ""), b.get("input") or {}
            path = str(inp.get("file_path") or inp.get("notebook_path") or "")
            if name in EDIT_TOOLS and ui.search(path):
                last_edit = i
            elif name == "Bash" and BASH_WRITE.search(str(inp.get("command", ""))) and any(
                    ui.search(tok) for tok in re.split(r"[\s'\"=(),]+", str(inp.get("command", "")))):
                last_edit = i
            elif ev.search(name):
                last_evidence = i
    if last_edit < 0 and changed_since(cwd, since, ui):
        last_edit = len(recs)
    if last_edit < 0 or last_evidence > last_edit or "![" in final_text:
        return "pass"
    if "[no-screenshot:" in final_text:
        return "exempt"
    return "block"


def selftest():
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps({"type": "user", "message": {"content": "改下按钮"}}) + "\n")
        f.write(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/x/src/Button.tsx"}},
            {"type": "text", "text": "改好了"}]}}) + "\n")
    v = verdict(f.name, dict(DEFAULTS))
    os.unlink(f.name)
    log(v, "selftest", selftest=True)
    print("ok" if v == "block" else f"FAIL: {v}")
    sys.exit(0 if v == "block" else 1)


def main():
    if "--selftest" in sys.argv:
        selftest()
    try:
        data = json.load(sys.stdin)
        if data.get("stop_hook_active") or not data.get("transcript_path"):
            return
        cfg = config()
        v = verdict(data["transcript_path"], cfg, data.get("cwd"))
        if v == "pass":
            return
        log(v, data.get("session_id", ""))
        if v == "block":
            print(json.dumps({"decision": "block", "reason": cfg["message"]}, ensure_ascii=False))
    except Exception:
        return


if __name__ == "__main__":
    main()
