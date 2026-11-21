#!/usr/bin/env python3
"""派发时机与结果（复盘用，只读）：把主会话 transcript 里的派发和台账结果关联起来。

  timing.py [--since YYYY-MM-DD[THH:MM+08:00]]   # 默认近 30 天；建议从你启用 claude-lead 的时刻算起

1. 按「派发前主会话读了多少」分桶，看侦察 / 施工的一次通过、最终通过、轮次、手修、非通过原因：
   判断派早了会不会因为我没摸清而返工，派晚了有没有换来更好的结果。
2. 按 delegate-nudge 的规则（仓库 hooks/posttool_delegate_nudge.py）在每个会话上复算提醒点，统计提醒后
   20 次调用内是否派发、派出去的结果，以及没派、继续自己读了多少次——用来调阈值。
读取口径和 hook 一致：派发或写操作清零；Skill / ToolSearch 等不计。只统计主会话（跳过 sidechain）。
"""
import argparse, collections, datetime as dt, glob, importlib.util, json, os, re

REC = os.path.expanduser("~/.local/state/agent-delegate/records.jsonl")
# 本脚本在 <repo>/skills/claude-lead/scripts/，hook 在 <repo>/hooks/；软链安装时按真实路径找，也可用 NUDGE_HOOK 指定
HOOK = os.environ.get("NUDGE_HOOK") or os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "..", "hooks", "posttool_delegate_nudge.py")
spec = importlib.util.spec_from_file_location("nudge", HOOK); nudge = importlib.util.module_from_spec(spec); spec.loader.exec_module(nudge)
FOLLOW = 20


def load_records():
    recs = [json.loads(l) for l in open(REC) if l.strip()] if os.path.exists(REC) else []
    idx, bytask = [], collections.defaultdict(list)
    for r in recs:
        bytask[r.get("task_id") or r.get("task")].append(r)
        m = re.search(r"(\d{8}-\d{6})-\w+?-(.+)$", os.path.basename((r.get("run") or "").rstrip("/")))
        if m:
            idx.append((dt.datetime.strptime(m.group(1), "%Y%m%d-%H%M%S"), m.group(2), r))
    return idx, bytask


def outcome(idx, bytask, label, when):
    cand = [r for t, l, r in idx if l == label and abs((t - when).total_seconds()) < 900]
    if not cand:
        return None
    tid = cand[0].get("task_id") or cand[0].get("task")
    rs = bytask[tid]; v = [z.get("verdict") for z in rs]
    return dict(tid=tid, date=rs[0].get("date"), rounds=len(rs), onepass=len(rs) == 1 and v[0] == "pass" and not rs[0].get("hand_fixed"),
                final=v[-1] == "pass", hand=any(z.get("hand_fixed") for z in rs),
                cause=[z["cause"] for z in rs if z.get("cause")])


def session_events(f):
    for l in open(f):
        try: d = json.loads(l)
        except ValueError: continue
        if d.get("isSidechain") or d.get("type") != "assistant": continue
        c = d["message"].get("content")
        if not isinstance(c, list): continue
        for x in c:
            if x.get("type") == "tool_use":
                yield d.get("timestamp"), x["name"], x.get("input") or {}


def main():
    default_since = (dt.datetime.now().astimezone() - dt.timedelta(days=30)).isoformat(timespec="seconds")
    ap = argparse.ArgumentParser(); ap.add_argument("--since", default=default_since); a = ap.parse_args()  # 启用 claude-lead 之前的会话不该计入
    since = dt.datetime.fromisoformat(a.since).timestamp()
    idx, bytask = load_records()
    dispatches, nudges, seen = [], [], set()
    for f in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")):
        if os.path.getmtime(f) < since: continue
        ev = [e for e in session_events(f) if e[0] and dt.datetime.fromisoformat(e[0].replace("Z", "+00:00")).timestamp() >= since]
        n = sess = 0; pend = []
        for i, (ts, name, inp) in enumerate(ev):
            k = nudge.kind(name, inp); cmd = inp.get("command", "") if isinstance(inp.get("command"), str) else ""
            if k == "reset" and "dispatch.sh" in cmd:
                m = re.search(r"dispatch\.sh\s+\S+\s+\S+\s+(\S+)\s+(\S+)", cmd)
                o = None
                if m and "RESUME=" not in cmd and "TASK=" not in cmd and ts:
                    when = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)  # run 目录名用本地时间
                    o = outcome(idx, bytask, m.group(2).strip("\"'"), when)
                    if o and o["tid"] not in seen:
                        seen.add(o["tid"]); dispatches.append(dict(o, kind=m.group(1).strip("\"'"), since=n, sess=sess))
                for p in pend:
                    if i - p["at"] <= FOLLOW and p["result"] is None: p["result"] = "dispatch"; p["o"] = o
            if k == "skip": continue
            if k == "reset":
                for p in pend:
                    if p["result"] is None: p["result"] = "write"; p["after"] = i - p["at"]
                n = 0; pend = [p for p in pend if p["result"] is None]
                continue
            n += 1; sess += 1
            if n % nudge.THRESHOLD == 0:
                p = dict(at=i, result=None, o=None, after=None); nudges.append(p); pend.append(p)
        for p in pend:
            if p["result"] is None: p["result"] = "end"; p["after"] = len(ev) - p["at"]

    ds = sorted(r["date"] for r in dispatches if r.get("date"))
    print(f"since {a.since}（按调用时间过滤）：关联到台账的新派任务 {len(dispatches)}，日期 {ds[0] if ds else '-'} ~ {ds[-1] if ds else '-'}（台账没记结论的派发不计）")
    b = lambda x: "0-14" if x < 15 else "15-29" if x < 30 else "30-59" if x < 60 else "60+"
    for kind, key, label in (("结论", "since", "派发前连续只读"), ("代码", "sess", "派发前本会话累计只读")):
        g = collections.defaultdict(list)
        for r in dispatches:
            if r["kind"] == kind: g[b(r[key])].append(r)
        print(f"== {kind} · 按{label}")
        for k in ("0-14", "15-29", "30-59", "60+"):
            L = g.get(k)
            if L:
                print(f"  {k:6} n={len(L):2} 一次通过 {sum(r['onepass'] for r in L)}/{len(L)} 最终通过 {sum(r['final'] for r in L)}/{len(L)} "
                      f"平均轮次 {sum(r['rounds'] for r in L)/len(L):.1f} 手修 {sum(r['hand'] for r in L)} 原因 {dict(collections.Counter(c for r in L for c in r['cause']))}")
    c = collections.Counter(p["result"] for p in nudges)
    print(f"== 提醒点复算（阈值 {nudge.THRESHOLD}）：共 {len(nudges)} 次；{FOLLOW} 次调用内派发 {c['dispatch']}，"
          f"转入写操作 {c['write']}，会话结束 {c['end']}")
    after = sorted(p["after"] for p in nudges if p["after"] is not None)
    if after:
        print(f"  没派的：提醒后到转入写操作或结束，中位 {after[len(after)//2]} 次、超过 30 次的 {sum(x > 30 for x in after)} 个（越多说明提醒后仍在主会话里长读）")
    od = [p["o"] for p in nudges if p["o"]]
    if od:
        print(f"  提醒后派出去且有台账的 {len(od)} 个：一次通过 {sum(o['onepass'] for o in od)}，最终通过 {sum(o['final'] for o in od)}")


if __name__ == "__main__":
    main()
