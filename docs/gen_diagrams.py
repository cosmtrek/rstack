#!/usr/bin/env python3
"""生成 README 里的两张设计框架图（SVG）。改文字或布局后重跑：python3 docs/gen_diagrams.py [输出目录，默认 docs/]"""
import sys
from html import escape
from pathlib import Path

BG = "#FAF9F5"
INK = "#141413"
MUTED = "#6F6B62"
CLAY = "#C9603F"       # Claude terracotta（线条、标题）
CLAY_SOFT = "#FBEAE3"  # 编号底色
GRAY = "#8A867C"
SAGE = "#6E8A55"
FONT = ("-apple-system, BlinkMacSystemFont, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', "
        "'Noto Sans CJK SC', 'Source Han Sans SC', 'WenQuanYi Zen Hei', 'Segoe UI', sans-serif")

STYLES = {
    "step":   dict(fill="#FFFFFF", stroke=CLAY, sw=1.6, dash=None),
    "plain":  dict(fill="#FFFFFF", stroke="#E4DFD4", sw=1.2, dash=None),
    "input":  dict(fill="#F0EDE5", stroke="#E4DFD4", sw=1.2, dash=None),
    "dyn":    dict(fill="#FFFFFF", stroke=SAGE, sw=1.6, dash=None),
    "static": dict(fill="#F0EDE5", stroke="#CBC5B8", sw=1.2, dash="4 3"),
    "record": dict(fill="#EEF3F8", stroke="#BACBDD", sw=1.2, dash=None),
}


def tw(s, size):
    """粗估文字宽度：CJK 按 1em，其余按 0.56em。"""
    return sum(size if ord(c) > 0x2E80 else size * 0.56 for c in s)


class SVG:
    def __init__(self, w, h, title):
        self.w, self.h, self.title, self.out = w, h, title, []

    def add(self, s):
        self.out.append(s)

    def text(self, x, y, s, size=12, color=INK, weight=400, anchor="start"):
        self.add(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" '
                 f'text-anchor="{anchor}">{escape(s)}</text>')

    def group(self, x, y, w, h, label, color=CLAY, lw=None):
        dash = "6 5"
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="none" stroke="{color}" '
                 f'stroke-width="1.3" stroke-dasharray="{dash}"/>')
        width = (lw or tw(label, 13)) + 22
        self.add(f'<rect x="{x + 12}" y="{y - 9}" width="{width}" height="18" fill="{BG}"/>')
        self.text(x + 23, y + 5, label, 13, color, 700)

    def box(self, x, y, w, h, title, lines=(), style="step", num=None, badge=None, tsize=15):
        st = STYLES[style]
        dash = f' stroke-dasharray="{st["dash"]}"' if st["dash"] else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{st["fill"]}" '
                 f'stroke="{st["stroke"]}" stroke-width="{st["sw"]}"{dash}/>')
        tx = x + 13
        ty = y + 23 if lines else y + h / 2 + 5
        if num:
            self.add(f'<rect x="{tx}" y="{ty - 14}" width="24" height="19" rx="9.5" fill="{CLAY_SOFT}"/>')
            self.text(tx + 12, ty, num, 11, CLAY, 700, "middle")
            tx += 32
        self.text(tx, ty, title, tsize, INK, 700)
        if badge:
            bw = tw(badge, 10) + 14
            bx = x + w - bw - 8
            self.add(f'<rect x="{bx}" y="{y - 9}" width="{bw}" height="18" rx="9" fill="#EAF1F8" '
                     f'stroke="#7FA3C6" stroke-width="1"/>')
            self.text(bx + bw / 2, y + 4, badge, 10, "#4D7AA6", 600, "middle")
        for i, line in enumerate(lines):
            self.text(x + 13, ty + 21 + i * 16, line, 11, MUTED)

    def arrow(self, pts, color=CLAY, dashed=False, label=None, lpos=None, head=True):
        d = "M" + " L".join(f"{a},{b}" for a, b in pts)
        mk = f' marker-end="url(#ah-{"c" if color == CLAY else "g"})"' if head else ""
        da = ' stroke-dasharray="4 4"' if dashed else ""
        self.add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.5"{da}{mk}/>')
        if label:
            lx, ly = lpos
            wl = tw(label, 11) + 10
            self.add(f'<rect x="{lx - wl / 2}" y="{ly - 10}" width="{wl}" height="16" fill="{BG}"/>')
            self.text(lx, ly + 2, label, 11, GRAY if color != CLAY else MUTED, 400, "middle")

    def render(self):
        defs = "".join(
            f'<marker id="ah-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
            for k, c in (("c", CLAY), ("g", GRAY)))
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" '
                f'height="{self.h}" font-family="{escape(FONT)}" role="img">'
                f'<title>{escape(self.title)}</title><defs>{defs}</defs>'
                f'<rect width="{self.w}" height="{self.h}" rx="16" fill="{BG}"/>'
                + "".join(self.out) + "</svg>\n")


def claude_lead():
    s = SVG(1000, 650, "claude-lead：Claude 当主管，codex 当执行者")
    # 左侧入口
    s.box(40, 78, 140, 42, "新任务", style="plain")
    s.box(40, 196, 140, 72, "读多了提醒", ["hook：连续 25 次只读", "只指向全局约定"], style="plain")
    # Claude 主会话
    s.group(200, 44, 760, 112, "Claude 主会话 · 想清楚")
    W, H, Y = 166, 66, 68
    xs = [216, 404, 600, 780]
    s.box(xs[0], Y, W, H, "判断", ["派不派、派侦察还是施工"], num="01")
    s.box(xs[1], Y, W, H, "写契约", ["几行到十几行，只写任务本身"], num="02")
    s.box(xs[2], Y, W, H, "复核", ["先读契约缺口，抽查证据"], num="04")
    s.box(xs[3], Y, W, H, "拍板 · 交付", ["取舍和用户定，对外写我做"], num="05")
    # codex
    s.group(200, 188, 760, 104, "codex · 看清楚", GRAY)
    s.box(404, 212, 322, 62, "侦察 · 施工", ["dispatch.sh 后台派发：工作区快照 + 契约 + 固定约束信封"], num="03")
    # 自迭代
    s.group(200, 324, 760, 112, "自迭代 · 越用越准", GRAY)
    s.box(216, 350, 216, 66, "调整", ["契约模板 · 技能规则 · 提醒阈值"], style="plain")
    s.box(468, 350, 216, 66, "复盘", ["stats · efficiency · timing.py"], style="plain")
    s.box(720, 350, 216, 66, "记账", ["ledger.py note 记结论和返工原因"], style="plain")

    s.arrow([(180, 99), (214, 99)])
    s.arrow([(382, 101), (402, 101)])
    s.arrow([(766, 101), (778, 101)])
    s.arrow([(180, 232), (196, 232), (196, 120), (214, 120)], GRAY, dashed=True, label="提醒", lpos=(196, 176))
    s.arrow([(487, 134), (487, 210)], label="契约", lpos=(487, 172))
    s.arrow([(680, 212), (680, 136)], label="结论 / 代码", lpos=(680, 172))
    s.arrow([(330, 350), (330, 136)], GRAY, dashed=True, label="改进", lpos=(330, 306))
    s.arrow([(744, 134), (744, 348)], GRAY, label="每轮", lpos=(744, 306))
    s.arrow([(720, 383), (686, 383)], GRAY)
    s.arrow([(468, 383), (434, 383)], GRAY)

    # 契约七栏
    s.group(40, 470, 920, 160, "契约 · 执行者按字面执行，每栏语义固定")
    cols = [("硬不变量", "核实过的规则", "对不上必停"),
            ("行为范围", "写行为和起点", "不写文件清单"),
            ("未决口径", "没拍板的取舍", "能问先问"),
            ("待核假设", "没亲手验证的", "动手前只读核"),
            ("业务风险", "红线与本次", "放行的写操作"),
            ("现场自决", "编号、命名等", "机械事实它定"),
            ("已知", "核实过的事实", "附来源和 id")]
    cw, gap = 118, 10
    for i, (t, a, b) in enumerate(cols):
        s.box(56 + i * (cw + gap), 494, cw, 70, t, [a, b], style="step" if i in (0, 3) else "plain", tsize=14)
    s.text(56, 590, "返工归因 cause：brief 契约 · env 环境 · capability 能力 · right_stop 本该停", 11.5, MUTED)
    s.text(56, 610, "契约缺口 gap：scope 范围画窄 · undecided 口径未定 · fact 事实写错 · external 外部行为不清 · conflict 约束冲突",
           11.5, MUTED)
    return s.render()


def weekly_retro():
    s = SVG(1000, 962, "weekly-retro：每周复盘，把 agent 的错误变成环境资产")
    # 输入
    s.group(38, 45, 180, 270, "输入 · 本机会话记录", GRAY)
    for i, (t, a) in enumerate([("Claude 会话", "所有仓库与 worktree"), ("Codex 会话", "含派出去的子任务"),
                                ("其他 agent", "无本地记录的按需补"), ("上期记录", "retro.md · 待验证改动")]):
        s.box(52, 64 + i * 61, 152, 54, t, [a], style="input", tsize=14)
    # 循环
    s.group(244, 45, 506, 270, "每周复盘循环")
    W, H = 112, 80
    X = [258, 382, 506, 630]
    row1 = [("01", "回填上期", ["判定上期改动", "有效或无效"]),
            ("02", "收集数据", ["scan.py 跑指标", "人工判读介入"]),
            ("03", "找失败点", ["介入、无效震荡", "高频高成本流程"]),
            ("04", "拐点归因", ["turn.py 看轨迹", "填四问卡"])]
    row2 = [("05", "分诊选药", ["感知 · 动作 · 反馈", "动态补丁优先"], None),
            ("06", "确认", ["每期 ≤5 条补丁", "逐条采纳或驳回"], "人拍板"),
            ("07", "落地验证", ["改技能仓库", "回放题重放"], None),
            ("08", "记账汇报", ["retro.md", "台账 · 指标"], None)]
    for x, (n, t, l) in zip(X, row1):
        s.box(x, 72, W, H, t, l, num=n, tsize=14)
    for x, (n, t, l, b) in zip(reversed(X), row2):
        s.box(x, 214, W, H, t, l, num=n, badge=b, tsize=14)
    s.arrow([(218, 112), (256, 112)], GRAY)
    for a, b in zip(X, X[1:]):
        s.arrow([(a + W, 112), (b - 2, 112)])
        s.arrow([(b, 254), (a + W + 2, 254)])
    s.arrow([(686, 152), (686, 212)])
    s.arrow([(314, 214), (314, 154)], dashed=True, label="下周回填", lpos=(314, 184))
    # 产出
    s.group(776, 45, 186, 270, "产出 · 环境资产", GRAY)
    for i, (t, a) in enumerate([("hook 拦截", "反馈层 · 走错当场提示"), ("脚本 / 工具", "动作层 · 多步连招封装"),
                                ("技能 / 全局约定", "感知层 · 入口和规则"), ("记忆", "事实、坐标 · 定期体检")]):
        s.box(790, 64 + i * 61, 158, 54, t, [a], style="dyn", tsize=14)
    s.arrow([(750, 180), (774, 180)], GRAY)

    # 事实源
    s.group(38, 356, 180, 262, "事实源 · 个人复盘目录", GRAY)
    for i, (t, a) in enumerate([("metrics.jsonl", "每期指标，跨期比率"), ("ledger/changes.md", "改动一行，下期回填"),
                                ("replays/ 回放题", "只读题 + 标准结论"), ("retro.md", "发现、决定、驳回理由")]):
        s.box(52, 374 + i * 59, 152, 52, t, [a], style="record", tsize=13.5)
    s.arrow([(314, 294), (314, 334), (204, 334), (204, 354)], GRAY, label="写入", lpos=(262, 334))
    # 图例
    for i, (st, t) in enumerate([("step", "循环步骤 / 问题分层"), ("dyn", "动态补丁、沉淀资产"),
                                 ("static", "静态补丁"), ("record", "记录 / 台账")]):
        y = 638 + i * 20
        c = STYLES[st]
        dash = f' stroke-dasharray="{c["dash"]}"' if c["dash"] else ""
        s.add(f'<rect x="40" y="{y}" width="26" height="13" rx="3" fill="{c["fill"]}" stroke="{c["stroke"]}" '
              f'stroke-width="{c["sw"]}"{dash}/>')
        s.text(74, y + 11, t, 11.5, MUTED)

    # 展开
    s.group(244, 356, 718, 362, "03–05 展开 · 问题怎么变成补丁")
    s.group(256, 384, 150, 318, "失败点（介入即失败）", GRAY)
    for i, (t, a) in enumerate([("用户纠正", "做错了，人来改"), ("追问进度、卡顿", "过程看不见"),
                                ("空确认", "不该停却停下来问"), ("自我更正、震荡", "同类调用反复失败"),
                                ("高频高成本流程", "没出错但步数多")]):
        s.box(266, 402 + i * 58, 130, 52, t, [a], style="input", tsize=13)
    s.box(422, 472, 152, 150, "拐点四问卡", ["看拐点那一刻的窗口", "缺信息 · 脏信息 · 假信号", "现象：做了 A，期望 B",
                                         "归因：缺了或多了什么", "下沉：哪个组件该喂信号", "验收：不靠人也能收敛"],
          style="plain", num="04", tsize=14)
    s.arrow([(406, 547), (420, 547)], GRAY)
    s.text(592, 400, "分层 · 症状", 12, MUTED, 700)
    s.text(720, 400, "动态补丁 · 优先", 12, MUTED, 700)
    s.text(848, 400, "静态补丁 · 兜底", 12, MUTED, 700)
    layers = [("感知层", ["找不到规则和入口", "被噪音淹没"], "前置检查脚本", ["一次输出关键事实", "截断和过滤输出"],
               "入口与约定", ["技能描述", "全局约定"]),
              ("动作层", ["工具不会用", "多步连招繁琐"], "封装成脚本", ["多步变一条命令", "收紧参数"],
               "已验证写法", ["CLI 速查技能", "已验证参数组合"]),
              ("反馈层", ["走错了自己不知道", "报错看不懂"], "hook 拦截", ["执行前拦下", "报错附修复提示"],
               "经验记忆", ["feedback /", "reference 记忆"])]
    for i, (a, al, b, bl, c, cl) in enumerate(layers):
        y = 412 + i * 92
        s.box(592, y, 118, 74, a, al, style="step", tsize=14)
        s.box(720, y, 118, 74, b, bl, style="dyn", tsize=14)
        s.box(848, y, 104, 74, c, cl, style="static", tsize=14)
        s.arrow([(710, y + 37), (718, y + 37)])
        s.arrow([(838, y + 37), (846, y + 37)], GRAY)
        s.arrow([(582, y + 37), (590, y + 37)], GRAY)
    s.arrow([(574, 547), (582, 547)], GRAY, head=False)
    s.arrow([(582, 449), (582, 633)], GRAY, head=False)
    s.text(592, 703, "hook 只管 Claude Code；也影响 Codex 的做成脚本；做不成动态才落静态", 11, MUTED)
    s.arrow([(686, 294), (686, 354)], GRAY, label="展开", lpos=(686, 326))

    # 指标
    s.group(38, 744, 924, 200, "02 观测指标 · 跨期比比率")
    metrics = [("纠正类介入 / 百条", ["用户纠正 agent", "人工判读，正则预标"], 1),
               ("追问进度 / 百条", ["用户追问进度、卡顿", "过程看不见的信号"], 1),
               ("空确认 / 百条", ["agent 停下来问", "用户只回「好的」"], 1),
               ("自我更正 / 千次", ["agent 收回结论", "先核实再下结论"], 1),
               ("查 --help / 千次", ["速查技能的覆盖度", "高频的补进速查"], 1),
               ("工具报错 / 千次", ["按 error_kinds 细分", "参数 / 过期 / 超时"], 1),
               ("被拦 / 千次", ["权限拒绝、安全检查", "沙箱与 hook 拦截"], 1),
               ("高频流程 flows", ["实例数、平均步数", "专用工具采用率"], 0),
               ("hook 命中", ["命中与豁免，先自测", "3 期零命中提议删"], 0),
               ("技能使用", ["skill_usage", "该走的技能走没走"], 0),
               ("回放通过率", ["无提示新会话做对没", "模型裁判 + 人工复核"], 0),
               ("记忆体检", ["超长、过期、矛盾", "索引大小前后对比"], 0)]
    for i, (t, l, rate) in enumerate(metrics):
        x = 52 + (i % 6) * 151
        y = 764 + (i // 6) * 78
        s.box(x, y, 141, 70, t, l, style="step" if rate else "plain", tsize=13.5)
    s.text(52, 932, "百条 = 每百条用户消息，千次 = 每千次工具调用；会话量每期差很多，跨期只比比率；介入类以人工判读为准",
           11, MUTED)
    return s.render()


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
    out.mkdir(parents=True, exist_ok=True)
    (out / "claude-lead.svg").write_text(claude_lead(), encoding="utf-8")
    (out / "weekly-retro.svg").write_text(weekly_retro(), encoding="utf-8")
