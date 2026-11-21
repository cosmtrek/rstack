#!/usr/bin/env python3
"""委托台账（运行状态，不进仓库）：~/.local/state/agent-delegate/records.jsonl

  ledger.py auto <run目录>      # dispatch.sh 结束时自动调用：按 meta 追加一行客观字段
  ledger.py note <run目录> --verdict pass|partial|fail|stop [--cause brief|env|capability|right_stop]
                 [--gap scope|undecided|fact|external|conflict] [--hand-fixed] --level 低|中|高 --task "一句话任务" --comment "一句话评价"
  ledger.py stats [--since YYYY-MM-DD]   # 按任务聚合的固定口径
  ledger.py list [--last N]
  ledger.py efficiency [--since YYYY-MM-DD]  # 执行效率、摩擦归因、主会话与派发 token 比例（复盘用）

verdict：stop = 中途停下待续派（要填 cause）；pass / partial / fail 是这一轮复核后的结论。
cause：brief = 我的契约写错或缺；env = 环境 / 凭证 / 基础设施；capability = 执行者能力；right_stop = 本该停下的取舍。
gap：cause=brief / right_stop 时契约缺在哪——scope 范围画窄漏了同一行为的其他入口；undecided 口径未定；
     fact 仓库事实写错或过期；external 外部系统真实行为不清、只做了离线验收；conflict 约束互相冲突。
hand_fixed：复核后我手动补改过它的产出。
"""
import argparse
import collections
import datetime
import json
import os
import re
import subprocess

DEFAULT_SINCE = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()

STATE = os.path.expanduser("~/.local/state/agent-delegate")
LEDGER = os.path.join(STATE, "records.jsonl")


def read_meta(run):
    meta = {}
    with open(os.path.join(run, "meta")) as f:
        for line in f:
            k, _, v = line.rstrip("\n").partition("=")
            meta[k] = v
    return meta


def load():
    if not os.path.exists(LEDGER):
        return []
    with open(LEDGER) as f:
        return [json.loads(l) for l in f if l.strip()]


def save(recs):
    with open(LEDGER, "w") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def branch_of(workdir):
    try:
        return subprocess.run(["git", "-C", workdir, "branch", "--show-current"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def task_of(r):
    """新记录有 task_id；旧记录按标签去掉 -r2 / -resume 等后缀归并。"""
    if r.get("task_id"):
        return r["task_id"]
    label = r.get("label") or r.get("task") or "?"
    return f"{r.get('date', '')[5:].replace('-', '')}-" + re.sub(r"-(r\d+|resume\d*)$", "", label)


def cmd_auto(a):
    m = read_meta(a.run)
    rec = {
        "date": datetime.date.today().isoformat(),
        "run": os.path.basename(a.run.rstrip("/")),
        "task_id": m.get("task"), "stage": m.get("stage"), "deliver": m.get("deliver"),
        "origin": m.get("origin"), "cli": "codex", "model": m.get("model"),
        "label": m.get("label"), "req": branch_of(m.get("workdir", ".")),
        "secs": int(m.get("secs") or 0), "exit": int(m.get("exit") or 0),
        "resume_of": m.get("resume_of") or None,
        "diffstat": m.get("diffstat") or None, "warn": m.get("warn") or None,
    }
    os.makedirs(STATE, exist_ok=True)
    with open(LEDGER, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def cmd_note(a):
    if a.verdict != "pass" and not a.cause:
        raise SystemExit("verdict 不是 pass 时要填 --cause")
    if a.cause in ("brief", "right_stop") and not a.gap:
        raise SystemExit("cause=brief / right_stop 时要填 --gap")
    name = os.path.basename(a.run.rstrip("/"))
    recs = load()
    for r in reversed(recs):
        if r.get("run") == name:
            r.update(verdict=a.verdict, cause=a.cause, gap=a.gap, hand_fixed=a.hand_fixed,
                     level=a.level, task=a.task, comment=a.comment)
            save(recs)
            return
    raise SystemExit(f"台账里没有 run={name}（dispatch 未自动记录？）")


def cmd_stats(a):
    recs = [r for r in load() if r.get("run") and r.get("date", "") >= a.since and "decision" not in r]
    tasks = collections.OrderedDict()
    for r in recs:
        tasks.setdefault(task_of(r), []).append(r)

    def group(rs):
        return f"{rs[0].get('origin') or '?'} · {rs[0].get('stage') or rs[0].get('mode') or '?'}"

    rows = collections.defaultdict(lambda: collections.Counter())
    causes = collections.defaultdict(collections.Counter)
    gaps = collections.Counter()
    unscored = []
    for tid, rs in tasks.items():
        last = rs[-1]
        if not last.get("verdict"):
            unscored.append(tid)
            continue
        g = group(rs)
        c = rows[g]
        c["任务"] += 1
        c["派发轮次"] += len(rs)
        c["秒"] += sum(r.get("secs", 0) for r in rs)
        if len(rs) == 1 and last["verdict"] == "pass" and not last.get("hand_fixed"):
            c["一次通过"] += 1
        if last["verdict"] == "pass":
            c["最终通过"] += 1
        if any(r.get("hand_fixed") for r in rs):
            c["手修"] += 1
        for r in rs:
            if r.get("cause"):
                causes[g][r["cause"]] += 1
            if r.get("gap"):
                gaps[r["gap"]] += 1

    print(f"口径：按任务聚合（同一 task 的多轮派发算一个任务）；一次通过 = 只派一轮、pass 且没手修。since={a.since}")
    for g, c in sorted(rows.items()):
        n = c["任务"]
        print(f"- {g}：任务 {n}，一次通过 {c['一次通过']}/{n}，最终通过 {c['最终通过']}/{n}，"
              f"平均轮次 {c['派发轮次'] / n:.1f}，手修 {c['手修']}，平均耗时 {c['秒'] // n}s，"
              f"非通过原因 {dict(causes[g]) or '无'}")
    if gaps:
        print(f"- 契约缺口分布：{dict(gaps.most_common())}")
    if unscored:
        print(f"- 未复核记账：{', '.join(unscored)}")


RUNS = os.path.expanduser("~/.local/share/agent-delegate/runs")
CLAUDE_PROJECTS = os.path.expanduser("~/.claude/projects")
# 环境 / 权限类摩擦：沙箱、凭证、网络。命中说明慢在脚本或权限，不在契约。
ENV_PAT = re.compile(r"read-only file system|Operation not permitted|Permission denied|AUTH_REQUIRED|"
                     r"no local token|not writable|sandbox (denied|blocked)|EACCES|connection refused|timed out|401 Unauthorized", re.I)


def run_events(run):
    """读一次派发的 codex 事件：token 用量、命令数、失败命令、环境类失败样例。"""
    out = {"in": 0, "cached": 0, "out": 0, "cmds": 0, "fail": 0, "env": 0, "env_samples": []}
    path = os.path.join(RUNS, run, "events.jsonl")
    if not os.path.exists(path):
        return None
    for line in open(path, errors="replace"):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if o.get("type") == "turn.completed":
            u = o.get("usage") or {}
            out["in"] += u.get("input_tokens", 0); out["cached"] += u.get("cached_input_tokens", 0)
            out["out"] += u.get("output_tokens", 0)
        it = o.get("item") or {}
        if o.get("type") == "item.completed" and it.get("type") == "command_execution":
            out["cmds"] += 1
            if str(it.get("exit_code")) not in ("0", "None"):
                out["fail"] += 1
                txt = (it.get("aggregated_output") or "")[-2000:]
                if ENV_PAT.search(txt):
                    out["env"] += 1
                    if len(out["env_samples"]) < 2:
                        out["env_samples"].append(ENV_PAT.search(txt).group(0))
    return out


def main_session_tokens(since):
    """Claude 主会话的 token（按 message.id 去重）。不含 codex。"""
    t = collections.Counter()
    cutoff = datetime.datetime.fromisoformat(since).timestamp()
    for root, _, files in os.walk(CLAUDE_PROJECTS):
        for fn in files:
            if not fn.endswith(".jsonl"):
                continue
            p = os.path.join(root, fn)
            if os.path.getmtime(p) < cutoff:
                continue
            seen = set()
            for line in open(p, errors="replace"):
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if o.get("type") != "assistant" or o.get("timestamp", "") < since:
                    continue
                m = o.get("message") or {}
                u = m.get("usage")
                if not u or m.get("id") in seen:
                    continue
                seen.add(m.get("id"))
                t["in"] += u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                t["cached"] += u.get("cache_read_input_tokens", 0)
                t["out"] += u.get("output_tokens", 0)
            t["sessions"] += 1 if seen else 0
    return t


def cmd_efficiency(a):
    recs = [r for r in load() if r.get("run") and r.get("date", "") >= a.since
            and not (r.get("label") or "").startswith("smoke")]
    rows = collections.defaultdict(collections.Counter)
    slow = []
    codex = collections.Counter()
    for r in recs:
        ev = run_events(r["run"])
        if not ev:
            continue
        g = r.get("stage") or "?"
        c = rows[g]
        c["轮"] += 1; c["秒"] += r.get("secs", 0); c["命令"] += ev["cmds"]; c["失败"] += ev["fail"]; c["环境失败"] += ev["env"]
        if r.get("cause"):
            c["因:" + r["cause"]] += 1
        for k in ("in", "cached", "out"):
            codex[k] += ev[k]
        slow.append((r.get("secs", 0), r["run"], ev, r.get("cause")))
    print(f"口径：since={a.since}，按派发轮次（不含 smoke）；环境失败 = 失败命令输出命中沙箱 / 凭证 / 网络特征。")
    for g, c in sorted(rows.items()):
        n = c["轮"]
        causes = {k[2:]: v for k, v in c.items() if k.startswith("因:")}
        print(f"- {g}：{n} 轮，平均 {c['秒'] // n}s，平均命令 {c['命令'] / n:.0f}，失败命令 {c['失败']}（环境类 {c['环境失败']}），"
              f"复核原因 {causes or '无'}")
    print("- 最慢 5 轮（秒 / run / 命令 / 失败 / 环境类 / 复核原因 / 环境样例）：")
    for secs, run, ev, cause in sorted(slow, key=lambda x: x[0], reverse=True)[:5]:
        print(f"  {secs}s {run} 命令 {ev['cmds']} 失败 {ev['fail']} 环境 {ev['env']} {cause or '-'} {ev['env_samples']}")
    m = main_session_tokens(a.since)
    tot_in = m["in"] + codex["in"]
    print(f"- token：主会话（Claude，{m['sessions']} 个会话）输入 {m['in'] / 1e6:.1f}M（缓存 {m['cached'] / 1e6:.1f}M）输出 {m['out'] / 1e6:.2f}M；"
          f"派发（codex）输入 {codex['in'] / 1e6:.1f}M（缓存 {codex['cached'] / 1e6:.1f}M）输出 {codex['out'] / 1e6:.2f}M；"
          f"派发占总输入 {codex['in'] / tot_in:.0%}" if tot_in else "- token：无数据")
    print("  注：两边模型单价不同，比例只看工作量分布；主会话含所有 Claude 会话（含其他工具开的子线程）。")


def cmd_list(a):
    for r in load()[-a.last:]:
        print(json.dumps(r, ensure_ascii=False))


p = argparse.ArgumentParser()
sub = p.add_subparsers(dest="cmd", required=True)
s = sub.add_parser("auto"); s.add_argument("run"); s.set_defaults(fn=cmd_auto)
s = sub.add_parser("note"); s.add_argument("run")
s.add_argument("--verdict", required=True, choices=["pass", "partial", "fail", "stop"])
s.add_argument("--cause", choices=["brief", "env", "capability", "right_stop"])
s.add_argument("--gap", choices=["scope", "undecided", "fact", "external", "conflict"])
s.add_argument("--hand-fixed", action="store_true")
s.add_argument("--level", required=True, choices=["低", "中", "高"])
s.add_argument("--task", required=True); s.add_argument("--comment", required=True)
s.set_defaults(fn=cmd_note)
s = sub.add_parser("stats"); s.add_argument("--since", default=DEFAULT_SINCE); s.set_defaults(fn=cmd_stats)
s = sub.add_parser("efficiency"); s.add_argument("--since", default=DEFAULT_SINCE); s.set_defaults(fn=cmd_efficiency)
s = sub.add_parser("list"); s.add_argument("--last", type=int, default=50); s.set_defaults(fn=cmd_list)
a = p.parse_args()
os.umask(0o077)
a.fn(a)
