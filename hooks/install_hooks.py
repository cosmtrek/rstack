#!/usr/bin/env python3
"""把本仓库的 hook 幂等地合并到 Claude Code 设置。改动前先备份。"""
import json
import os
import shlex
import shutil
import tempfile
import time
from pathlib import Path


def install(groups, script, matcher=None):
    command = f"python3 -I {shlex.quote(str(script))}"
    updated = []
    for group in groups:
        existing = group.get("hooks", [])
        kept = []
        for hook in existing:
            old = hook.get("command", "")
            # 仅识别历史安装器生成的直接调用，也接受旧版没有引号的路径。
            path = old.removeprefix("python3 -I ").strip("'\"")
            if (old.startswith("python3 -I ") and Path(path).is_absolute()
                    and Path(path).name == script.name
                    and old not in (command, f"python3 -I {script}")):
                continue
            if old == f"python3 -I {script}" and old != command:
                hook = dict(hook, command=command)
            kept.append(hook)
        if kept or not existing:
            updated.append(dict(group, hooks=kept) if kept != existing else group)
    if not any(group.get("matcher") == matcher and any(h.get("command") == command for h in group.get("hooks", []))
               for group in updated):
        entry = {"hooks": [{"type": "command", "command": command, "timeout": 5}]}
        if matcher is not None:
            entry["matcher"] = matcher
        updated.append(entry)
    return updated


def main():
    os.umask(0o077)
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser()
    path = (config / "settings.json").resolve()
    settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    before = json.dumps(settings)
    hooks = settings.setdefault("hooks", {})
    directory = Path(__file__).resolve().parent
    hooks["PreToolUse"] = install(hooks.get("PreToolUse", []), directory / "pretool_guard.py", matcher="Bash")
    hooks["PostToolUse"] = install(hooks.get("PostToolUse", []), directory / "posttool_delegate_nudge.py")
    if json.dumps(settings) == before:
        print("Hook 已安装。")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        stamp = time.strftime("%Y%m%d%H%M%S")
        with tempfile.NamedTemporaryFile(prefix=f"{path.name}.bak-{stamp}-", dir=path.parent, delete=False) as backup:
            shutil.copyfile(path, backup.name)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
        temporary = Path(f.name)
        try:
            json.dump(settings, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    print(f"已更新 Hook：{path}")


if __name__ == "__main__":
    main()
