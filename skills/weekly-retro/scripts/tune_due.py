#!/usr/bin/env python3
"""判断这一期复盘要不要顺带评估复盘本身（references/tune.md），每两期一次。

用法: python3 -I tune_due.py [--week 2026-W03]     # 缺省取当前 ISO 周
口径: 上次评估 = $RETRO_DIR/ledger/tune-log.md 里最近一个形如「2026-W03 评估」的标题；
      之后已写完 retro.md 的期数（不含本期）+ 本期 >= 2 就到期；从没评估过则从第一期算。
输出: 一行 DUE / NOT_DUE 加依据。只读。
"""
import argparse, datetime, glob, os, re

RETRO = os.path.expanduser(os.environ.get("RETRO_DIR") or "~/notes/retro")
LOG = os.path.join(RETRO, "ledger", "tune-log.md")
EVERY = 2


def key(week):
    y, w, sub = re.fullmatch(r"(\d{4})-W(\d{1,2})([a-z]?)", week).groups()
    return int(y), int(w), sub


def main():
    ap = argparse.ArgumentParser()
    y, w, _ = datetime.date.today().isocalendar()
    ap.add_argument("--week", default=f"{y}-W{w:02d}")
    cur = key(ap.parse_args().week)

    last = None
    if os.path.exists(LOG):
        found = re.findall(r"^##.*?(\d{4}-W\d{1,2}[a-z]?) 评估", open(LOG, encoding="utf-8").read(), re.M)
        if found:
            last = max(key(x) for x in found)

    done = sorted(key(os.path.basename(os.path.dirname(p)))
                  for p in glob.glob(os.path.join(RETRO, "[0-9]*-W*", "retro.md")))
    since = [k for k in done if k < cur and (last is None or k > last)]
    n = len(since) + (0 if last == cur else 1)
    fmt = lambda k: f"{k[0]}-W{k[1]:02d}{k[2]}"
    basis = (f"上次评估 {fmt(last) if last else '无'}；之后已完成 {[fmt(k) for k in since]}，"
             f"连本期 {fmt(cur)} 共 {n} 期，每 {EVERY} 期评估一次")
    print(("DUE " if n >= EVERY else "NOT_DUE ") + basis)


if __name__ == "__main__":
    main()
