#!/usr/bin/env python3
"""判断这一期复盘要不要顺带评估复盘本身（references/tune.md），每两期一次。

用法: python3 -I tune_due.py [--week 2026-W03]     # 缺省取当前 ISO 周
口径: RETRO_DIR 默认 $RSTACK_HOME/retro（RSTACK_HOME 默认 ~/.rstack）。
      上次评估 = $RETRO_DIR/ledger/tune-log.md 里最近一个形如「2026-W03 评估」的标题；
      之后已写完 retro.md 的期数（不含本期）+ 本期 >= 2 就到期；从没评估过则从第一期算。
      目录名不是 <年>-W<周>[小写字母] 的（如 2026-W03-draft、备份目录）不计。
输出: 一行 DUE / NOT_DUE 加依据。只读。
"""
import argparse, datetime, glob, os, re

RETRO = os.path.expanduser(os.environ.get("RETRO_DIR")
                           or os.path.join(os.environ.get("RSTACK_HOME") or "~/.rstack", "retro"))
LOG = os.path.join(RETRO, "ledger", "tune-log.md")
EVERY = 2


def key(week):
    """「2026-W03」「2026-W3b」→ (2026, 3, 'b')；格式不对返回 None。"""
    m = re.fullmatch(r"(\d{4})-W(\d{1,2})([a-z]?)", week)
    return (int(m.group(1)), int(m.group(2)), m.group(3)) if m else None


def main():
    ap = argparse.ArgumentParser()
    y, w, _ = datetime.date.today().isocalendar()
    ap.add_argument("--week", default=f"{y}-W{w:02d}")
    week = ap.parse_args().week
    cur = key(week)
    if cur is None:
        ap.error(f"--week 应为 <年>-W<周>，例如 2026-W03：{week}")

    last = None
    if os.path.exists(LOG):
        found = re.findall(r"^##.*?(\d{4}-W\d{1,2}[a-z]?) 评估", open(LOG, encoding="utf-8").read(), re.M)
        if found:
            last = max(key(x) for x in found)

    done = sorted(k for k in (key(os.path.basename(os.path.dirname(p)))
                              for p in glob.glob(os.path.join(glob.escape(RETRO), "[0-9]*-W*", "retro.md"))) if k)
    since = [k for k in done if k < cur and (last is None or k > last)]
    n = len(since) + (0 if last == cur else 1)
    fmt = lambda k: f"{k[0]}-W{k[1]:02d}{k[2]}"
    basis = (f"上次评估 {fmt(last) if last else '无'}；之后已完成 {[fmt(k) for k in since]}，"
             f"连本期 {fmt(cur)} 共 {n} 期，每 {EVERY} 期评估一次")
    print(("DUE " if n >= EVERY else "NOT_DUE ") + basis)


if __name__ == "__main__":
    main()
