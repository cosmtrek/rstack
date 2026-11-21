#!/usr/bin/env python3
"""只读扫描一段时间内的 Claude Code 与 Codex 会话记录，产出复盘用的指标和样本。

用法: python3 -I scan.py --since 2026-11-02 [--until 2026-11-09] [--out <目录>] [--include-retro]
产物:
  <out>/metrics.json  固定指标，用于跨周对比（含每千次工具调用的比率 rates，窗口长短不同时比这个）；flows 是高频高成本流程
  <out>/samples.md    每类样本，按会话轮流取，避免被单个会话占满
  <out>/turns.tsv     窗口内所有短的用户消息（时间 / 来源 / 会话 / 标签 / 原文），介入判读以它为准
指标口径改动要同步改 METRICS_VERSION 并写进 tune-log，否则跨周对比失真。
环境相关的配置（常用 CLI、速查技能、流程领域表、反复出现的 ID 形状）放在 $RETRO_CONFIG 或 $RETRO_DIR/config.json，
格式见 config.example.json；没有配置文件时用下面的通用默认值。
"""
import argparse, collections, datetime as dt, glob, json, os, re

METRICS_VERSION = 6
# v2: 按记录时间戳筛选、覆盖统计；v3: 用户消息分推进/介入，读 hook 命中日志
# v4: 默认排除复盘会话；介入正则只做预标注，另出 turns.tsv 供人工判读；新增空确认、技能使用、
#     help 会话是否加载过速查技能、报错细分、每千次工具调用比率；Codex 拦截只认明确的拒绝文本；样本按会话轮流取
# v5: 新增 flows（高频高成本流程）：不看成败，按「流程实例 × 平均步数」找每次都要很多步的同类操作，
#     附跨会话反复出现的 ID / 坐标、临时手写的 JWT/curl 包装脚本、各领域专用工具的采用率、耗时；
#     复盘会话不再整条排除，只丢掉发起复盘之后的记录；原有指标只受这一条影响
# v6: 兼容自定义会话目录和新版 Hook 日志，补计委派提醒，移除环境专用的流程排除项
SELF_CORR = re.compile(r'[^。\n]*(更正|我说错|说错了|看反|是我看错|收回|我上一条|我上次说|之前说的不对|不是我之前说的|我前面说过)[^。\n]*')
USER_CORR = re.compile(r'(不对|不是这样|错了|看错|搞错|说错|看反|没理解|没太理解|不要写|不用写|别再|只想看|只解决|先停|停掉|不是我要的'
                       r'|为啥不是|为什么不是|不用找|不用管|不要用|应该是.{0,30}吧|你直接改|直接改|写死|需要你修复|不行么|只需要|按照规范|不要干预|不要限制|尽量简短|等部署好|给个结论)')
USER_OBS = re.compile(r'(卡在哪|为啥这么慢|为什么这么慢|怎么这么慢|现在什么情况|现在是什么情况|在跑.{0,6}么|还在跑|跑完了?么|推送了么|怎么还没'
                      r'|进展现在是啥|是不是结束了|有啥异常么|改了么|是不是.{0,8}过期|这个是改哪个|进展怎么样|进度怎么样)')
# 空确认：agent 停下来问、用户只回一句同意，没有新信息。多了说明 agent 在不必要的地方停
EMPTY_OK = re.compile(r'^(好的?|行|可以的?|嗯)?[，, ]*(那就?)?(提交|推送|推|修|改|加上|开干|开搞|继续|绑定|精简|删掉|修一下|改下|修复下|全部确认|按照你的建议来|接着干)?'
                      r'(一下)?(吧|下吧)?[。！ ]*$')
CL_DENY = re.compile(r'denied|auto mode classifier|not allowed|Blocked:|安全检查|safety check', re.I)
CX_DENY = re.compile(r'sandbox.{0,20}den|rejected by user|was not approved|blocked by policy', re.I)
RETRO_DIR = os.path.expanduser(os.environ.get('RETRO_DIR') or '~/notes/retro')

def load_config():
    here = os.path.dirname(os.path.realpath(__file__))
    configured = os.environ.get('RETRO_CONFIG')
    paths = [os.path.join(RETRO_DIR, 'config.json'), os.path.join(here, '..', 'config.json')]
    for p in [os.path.expanduser(configured)] if configured else paths:
        if configured or os.path.exists(p):
            with open(p, encoding='utf-8') as f:
                return json.load(f)
    return {}
CFG = load_config()
# 统计 `<cli> <子命令> --help` 的 CLI 列表：填你常用、且有速查技能覆盖的那几个
HELP_CLIS = CFG.get('help_clis') or ['gh', 'kubectl', 'docker', 'aws', 'gcloud']
HELP = re.compile(r'((?:' + '|'.join(map(re.escape, HELP_CLIS)) + r')\s+[\w+.-]+(?:\s+[\w+.-]+)?)\s+(?:--help|-h\b)')
RETRO_RUN = re.compile(r"""weekly-retro/scripts/(?:scan|replay)\.py(?:\\?['"])?\s+--""")
RETRO_CMD = re.compile(r'<command-name>/?weekly-retro</command-name>')
SKILL_PATH = re.compile(r'skills/([\w-]+)/(?:SKILL\.md|scripts/[\w.-]+)')
CHEATSHEET = CFG.get('cheatsheet_skill')  # CLI 速查技能名；help 会话里加载过它的比例说明速查有没有被用上
SKIP_USER = ('<', '[Request', 'Base directory for this skill', 'This session is being continued', 'Delegated task', '# AGENTS.md', 'Context handoff', '[Historical')

def parse_ts(d):
    t = d.get('timestamp')
    if not isinstance(t, str): return None
    try: return dt.datetime.fromisoformat(t.replace('Z', '+00:00')).timestamp()
    except ValueError: return None

_ROOTS = {}
def repo_root(cwd):
    # 归到所在仓库 / worktree 根目录（含 .git 文件或目录）；不在仓库里就用原路径
    if cwd in _ROOTS: return _ROOTS[cwd]
    p = cwd
    while p and p != '/':
        if os.path.exists(os.path.join(p, '.git')): break
        p = os.path.dirname(p)
    _ROOTS[cwd] = r = (p if p and p != '/' else cwd).replace(os.path.expanduser('~'), '~')
    return r

def text_of(c):
    if isinstance(c, str): return c
    if isinstance(c, list):
        return ' '.join(x.get('text', '') for x in c if isinstance(x, dict))
    return ''

def err_kind(name, txt):
    if 'Blocked: sleep' in txt: return 'sleep_blocked'
    if 'removal safety check' in txt: return 'rm_safety'
    if 'InputValidationError' in txt or 'Invalid parameters' in txt: return 'bad_params'
    if 'CLI_PARSE_ERROR' in txt or 'unknown option' in txt: return 'cli_parse'
    if 'modified since read' in txt or 'has not been read' in txt or 'String to replace not found' in txt: return 'edit_stale'
    if 'Exit code 144' in txt or 'timed out' in txt: return 'killed_or_timeout'
    return 'bash_nonzero' if name == 'Bash' else 'other'


# ---- 高频高成本流程（v5）----
# 失败拐点和用户纠正看不到「没出错但每次都很费劲」的流程（例：拉群消息 → 排查 → 回复，每次 4~17 步）。
# 做法：会话按用户消息切成任务段；每条命令归成「领域」；同一会话里相邻任务段（隔 ≤3 段、<60 分钟）
# 都用到该领域就合并成一个流程实例；按 实例数 × 平均步数 排序。
# (匹配命令原文的正则, 领域, 该领域的专用工具正则或 None)。按顺序匹配；匹配不上的按「程序 子命令」自动成族，新模式也能冒出来。
# 默认只给几个通用示例，真正有用的领域表放 config.json 的 domains（见 config.example.json）。
DOMAINS = [tuple(d) for d in CFG.get('domains', [])] or [
    (r'\bgh\s+(?:pr|run|issue)\b', 'GitHub PR / CI', None),
    (r'\bkubectl\b', 'Kubernetes', None),
    (r'\bdocker\b', 'Docker', None),
    (r'\bcurl\b[^|;&\n]*(?:Authorization|Bearer)', '带鉴权调接口', None),
]
FLOW_SKIP = re.compile(r'^(?:git|go|gofmt|bun|npm|pnpm|node|npx|make|ci\.sh|vitest|pytest|python3?|cargo|tsc|eslint|dispatch\.sh|ledger\.py)$')
TRIVIAL = set('cat sed head tail grep rg ls echo jq wc find sort awk cut printf true sleep date xargs tee tr uniq diff stat realpath '
              'basename dirname test export set source cd pwd which command type mkdir cp mv rm touch chmod ln env timeout nl column '
              'readlink du ps kill sha256sum base64 for do done if then fi while else elif exit read local seq until func function'.split())
# 跨会话反复手写的 ID / 坐标（群 id、环境名、资源 id……），每次都要重新查就说明缺一个入口。按你的环境改 entity_regex（要有一个捕获组）。
ENTITY = re.compile(CFG.get('entity_regex') or r'\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|--(?:task|run|job)[_-]id[ =]\S{4,})')
# 临时手写的接口包装脚本：写了 .sh / .py 文件、内容里带鉴权头。多了说明缺一个统一的调用工具
WRAPPER = re.compile(r'(?:cat|tee)\s*>\s*\S+\.(?:sh|py)\b[\s\S]{0,4000}?(?:' + (CFG.get('wrapper_regex') or r'Authorization:|Bearer |-Token:') + ')', re.I)

def cmd_family(cmd, env):
    """命令 → (领域, 签名)。会话内记住 S=~/x/tool.py 这类变量再展开，否则 "$S send" 认不出来。"""
    for k, v in re.findall(r'(?:^|[\s;&(])([A-Z_][A-Z0-9_]*)=["\']?([~/][^\s"\';&)]+)', cmd): env[k] = v
    cmd = re.sub(r'"?\$\{?([A-Z_][A-Z0-9_]*)\}?"?', lambda m: env.get(m.group(1), m.group(0)), cmd)
    body = re.sub(r'<<\s*[\'"]?(\w+)[\'"]?.*?\n\1\b', ' ', cmd, flags=re.S)  # heredoc 内容不算命令
    for p, d, _ in DOMAINS:
        if re.search(p, body, re.M): return d, d + ' ' + _sig(body)
    s = _sig(body)
    if not s or FLOW_SKIP.match(s.split()[0]): return None, s
    return (s.split()[0] if s.split()[0].endswith(('.py', '.sh', '.js')) else ' '.join(s.split()[:2])), s  # 脚本按脚本名成族

def _sig(body):
    for seg in re.split(r'\|\||&&|;|\||\n|\$\(', body):
        toks = [t for t in re.split(r'\s+', seg.strip()) if t and t not in '(){}']
        while toks and (re.match(r'^\w+=', toks[0]) or toks[0] in ('sudo', 'exec', 'time', 'nohup', 'env', 'timeout') or toks[0].isdigit()): toks.pop(0)
        if not toks or os.path.basename(toks[0]) in TRIVIAL: continue
        prog, rest = os.path.basename(toks[0].strip('"\'')), toks[1:]
        if prog.startswith(('python', 'bash', 'sh', 'node')) and rest and not rest[0].startswith('-'):
            prog, rest = os.path.basename(rest[0].strip('"\'')), rest[1:]
        sub = [t for t in rest if re.match(r'^\+?[a-z][\w-]{1,30}$', t)][:2]
        return ' '.join([prog] + sub)
    return ''

class Flows:
    def __init__(self): self.eps = []; self.env = {}
    def session(self, src): self.env = {}; self.src = src; self.cur = None
    def user(self, ts, text): self.eps.append({'src': self.src, 'ts': ts, 'user': text[:80].replace('\n', ' '), 'calls': []}); self.cur = self.eps[-1]
    def call(self, ts, cmd):
        if self.cur is None: self.user(ts, '(会话开头)')
        dom, sig = cmd_family(cmd, self.env)
        self.cur['calls'].append((dom, sig, cmd, ts))
    def report(self, top=12):
        inst, last = collections.defaultdict(list), {}
        for i, e in enumerate(self.eps):
            for d, n in collections.Counter(c[0] for c in e['calls'] if c[0]).items():
                j = last.get(d); prev = self.eps[j] if j is not None else None
                if prev and prev['src'] == e['src'] and e['ts'] - prev['ts'] < 3600 and i - j <= 3: inst[d][-1].append((i, n))
                else: inst[d].append([(i, n)])
                last[d] = i
        mins = collections.Counter()  # 每次调用记到下一次调用为止的时间（含等待和思考），单次封顶 10 分钟
        for e in self.eps:
            for c, nx in zip(e['calls'], e['calls'][1:]):
                if c[0]: mins[c[0]] += min(nx[3] - c[3], 600) / 60
        tools = {d: t for _, d, t in DOMAINS if t}
        rows = []
        for d, fl in inst.items():
            steps = [sum(n for _, n in f) for f in fl]
            if len(fl) < 3: continue
            idx = [i for f in fl for i, _ in f]; calls = [c for i in idx for c in self.eps[i]['calls'] if c[0] == d]
            worst = max(fl, key=lambda f: sum(n for _, n in f))
            rows.append({'domain': d, 'instances': len(fl), 'sessions': len({self.eps[i]['src'] for i in idx}), 'steps': sum(steps),
                         'mean_steps': round(sum(steps) / len(fl), 1), 'max_steps': max(steps), 'score': sum(steps), 'minutes': round(mins[d]),
                         'tool_share': (round(sum(any(re.search(tools[d], c[2]) for i, _ in f for c in self.eps[i]['calls']) for f in fl) / len(fl), 2) if d in tools else None),
                         'help': sum(bool(re.search(r'--help|\s-h(?:\s|$)', c[2])) for c in calls),
                         'top_sigs': collections.Counter(c[1] for c in calls).most_common(4),
                         'example': {'src': self.eps[worst[0][0]]['src'], 'user': self.eps[worst[0][0]]['user'],
                                     'seq': [c[1][:50] for i, _ in worst for c in self.eps[i]['calls'] if c[0]][:15]}})
        rows.sort(key=lambda r: -r['score'])
        ents = collections.defaultdict(lambda: [set(), collections.Counter()])
        wrappers = collections.Counter()
        for e in self.eps:
            for d, sig, cmd, _ in e['calls']:
                for m in set(ENTITY.findall(cmd)): ents[m][0].add(e['src']); ents[m][1][d or sig.split(' ')[0]] += 1
                if WRAPPER.search(cmd): wrappers[e['src']] += 1
        ent_rows = sorted(([k, len(v[0]), sum(v[1].values()), v[1].most_common(2)] for k, v in ents.items() if len(v[0]) >= 3), key=lambda r: -r[1])
        return {'top': rows[:top], 'repeated_entities': ent_rows[:12],
                'adhoc_wrappers': {'scripts': sum(wrappers.values()), 'sessions': len(wrappers)}}

class Acc:
    def __init__(self):
        self.B = collections.defaultdict(lambda: {'count': 0, 'samples': collections.defaultdict(list)})
        self.M = collections.Counter(); self.C = collections.defaultdict(lambda: {'sessions': set(), 'branches': set()})
        self.turns = []; self.skills = collections.Counter(); self.errk = collections.Counter()
        self.help_cmd = collections.Counter(); self.help_sess = set(); self.sheet_sess = set(); self.excluded = []; self.F = Flows()
    def add(self, key, sample, src):
        self.B[key]['count'] += 1
        s = self.B[key]['samples'][src]
        if len(s) < 6: s.append(sample[:220].replace('\n', ' '))
    def cover(self, cwd, branch, sid):
        if not cwd: return
        k = repo_root(cwd); self.C[k]['sessions'].add(sid)
        if branch: self.C[k]['branches'].add(branch)
    def user(self, ts, kind, src, text):
        # 介入 = 纠正 agent 或追问进度 / 卡顿；拍板、补需求、改范围算推进。正则只是预标注，判读看 turns.tsv
        # 长消息多是 agent 写给子线程的任务说明（在子会话里以 user 身份出现），不算人的输入
        self.M['user_turns'] += 1
        t = text.strip()
        if len(t) > 300: return
        tag = ''
        if EMPTY_OK.match(t): tag = '空确认'; self.add('empty_confirm', t, src)
        elif USER_CORR.search(t): tag = '纠正?'; self.add('intervention_correction', t, src)
        elif USER_OBS.search(t): tag = '追问?'; self.add('intervention_observability', t, src)
        self.turns.append((ts, kind, src, tag, t.replace('\t', ' ').replace('\n', ' ⏎ ')))
    def skill(self, name, src):
        self.skills[name] += 1
        if CHEATSHEET and name == CHEATSHEET: self.sheet_sess.add(src)
    def helps(self, cmd, src):
        for h in HELP.findall(cmd):
            self.add('help_lookup', h, src); self.help_cmd[h] += 1; self.help_sess.add(src)
        for m in SKILL_PATH.finditer(cmd): self.skill(m.group(1), src)

def retro_start(path):
    """复盘会话 = 用户用 /weekly-retro 发起，或会话里真的执行过扫描 / 回放脚本。返回第一次发起的时间戳，
    之后的记录不计（它们引用的例子会被重复计数），之前的正常开发照常统计。只读过、改过技能文件的会话不算。"""
    try:
        for line in open(path, errors='ignore'):
            if 'weekly-retro' not in line: continue
            try: d = json.loads(line)
            except Exception: continue
            p = d.get('payload') or {}; c = (d.get('message') or {}).get('content') or p.get('content'); hit = False
            if d.get('type') == 'user' or p.get('role') == 'user':
                hit = bool(RETRO_CMD.search(text_of(c)[:2000]))
            if p.get('type') in ('function_call', 'custom_tool_call', 'local_shell_call') and RETRO_RUN.search(json.dumps(p)): hit = True
            for b in c if isinstance(c, list) else []:
                if isinstance(b, dict) and b.get('type') == 'tool_use' and RETRO_RUN.search(str((b.get('input') or {}).get('command', ''))): hit = True
            if hit: return parse_ts(d) or 0
    except OSError: pass
    return None

def scan_claude(files, A, W0):
    for f, cut in files:
        W = (W0[0], min(W0[1], cut))
        src = 'cl:' + os.path.basename(f)[:8]; names = {}; A.F.session(src)
        for line in open(f, errors='ignore'):
            try: d = json.loads(line)
            except Exception: continue
            x = parse_ts(d)
            if x is None or not (W[0] <= x < W[1]) or d.get('isSidechain'): continue
            A.cover(d.get('cwd'), d.get('gitBranch'), src)
            c = (d.get('message') or {}).get('content'); role = d.get('type')
            if role == 'user' and isinstance(c, str) and not d.get('isMeta'):
                if not c.startswith(SKIP_USER): A.user(x, 'claude', src, c); A.F.user(x, c)
            if not isinstance(c, list): continue
            for b in c:
                if not isinstance(b, dict): continue
                t = b.get('type')
                if t == 'tool_use':
                    names[b.get('id')] = b.get('name'); A.M['tool_calls'] += 1; i = b.get('input') or {}
                    if b.get('name') == 'Skill' and i.get('skill'): A.skill(i['skill'], src)
                    elif b.get('name') == 'Read':
                        m = SKILL_PATH.search(str(i.get('file_path')))
                        if m: A.skill(m.group(1), src)
                    elif b.get('name') == 'Bash': A.helps(i.get('command', ''), src); A.F.call(x, i.get('command', ''))
                elif t == 'tool_result' and b.get('is_error'):
                    txt = text_of(b.get('content')).replace('\n', ' '); n = names.get(b.get('tool_use_id'), '?')
                    k = err_kind(n, txt); A.errk[k] += 1
                    A.add('denied' if (k in ('sleep_blocked', 'rm_safety') or CL_DENY.search(txt[:300])) else 'tool_error', f"[{n}] {txt}", src)
                elif t == 'text' and role == 'assistant':
                    for m in SELF_CORR.finditer(b.get('text', '')): A.add('self_correction', m.group(0), src)
                elif t == 'text' and role == 'user' and not d.get('isMeta'):
                    s = b.get('text', '')
                    if s and not s.startswith(SKIP_USER): A.user(x, 'claude', src, s); A.F.user(x, s)

def scan_codex(files, A, W0):
    for f, cut in files:
        W = (W0[0], min(W0[1], cut))
        src = 'cx:' + os.path.basename(f)[-18:-6]; cwd = None; A.F.session(src)
        for line in open(f, errors='ignore'):
            try: d = json.loads(line)
            except Exception: continue
            p = d.get('payload') or {}
            if d.get('type') in ('session_meta', 'turn_context'): cwd = p.get('cwd') or cwd
            x = parse_ts(d)
            if x is None or not (W[0] <= x < W[1]): continue
            A.cover(cwd, None, src)
            if d.get('type') != 'response_item': continue
            pt = p.get('type')
            if pt == 'message':
                txt = text_of(p.get('content'))
                if p.get('role') == 'user' and txt and not txt.startswith(SKIP_USER): A.user(x, 'codex', src, txt); A.F.user(x, txt)
                elif p.get('role') == 'assistant':
                    for m in SELF_CORR.finditer(txt): A.add('self_correction', m.group(0), src)
            elif pt in ('function_call', 'custom_tool_call', 'local_shell_call'):
                A.M['tool_calls'] += 1; A.helps(json.dumps(p, ensure_ascii=False), src)
                for cm in codex_cmds(p): A.F.call(x, cm)
            elif pt in ('function_call_output', 'custom_tool_call_output'):
                out = json.dumps(p.get('output', ''), ensure_ascii=False)
                if CX_DENY.search(out[:600]): A.add('denied', out.replace('\\n', ' '), src)

def codex_cmds(p):
    # Codex 的 exec 是一段 JS，里面可能有多次 tools.exec_command({cmd: "..."})；function_call 的参数是 JSON
    raw = p.get('input') or p.get('arguments') or ''
    out = []
    for m in re.finditer(r'\b(?:cmd|command)"?\s*:\s*("(?:[^"\\]|\\.)*")', raw):
        try: out.append(json.loads(m.group(1)))
        except ValueError: pass
    return out

def hook_hits(W):
    path = os.path.expanduser('~/.local/state/agent-hooks/hits.jsonl'); out = collections.Counter()
    if not os.path.exists(path): return {}
    for line in open(path):
        try:
            d = json.loads(line)
            stamp = re.sub(r'([+-]\d{2})(\d{2})$', r'\1:\2', d['ts'])
            x = dt.datetime.fromisoformat(stamp).timestamp()
        except Exception: continue
        if not (W[0] <= x < W[1]): continue
        kind = 'selftest' if d.get('selftest') or 'retro-selftest' in (d.get('command') or '') else d.get('decision')
        out[f"{d.get('rule')}:{kind}"] += 1
    return dict(out)

def spread(samples, n=20):
    # 按会话轮流取样本，单个会话不会占满
    out, pools = [], [(src, list(v)) for src, v in samples.items()]
    while pools and len(out) < n:
        for src, v in list(pools):
            if v and len(out) < n: out.append(f"{v.pop(0)}  〔{src}〕")
            if not v: pools.remove((src, v))
    return out

KEYS = ('self_correction', 'intervention_correction', 'intervention_observability', 'empty_confirm', 'help_lookup', 'denied', 'tool_error')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', required=True); ap.add_argument('--until')
    ap.add_argument('--out', help='报告目录，默认 $RETRO_DIR/<年>-W<周>（RETRO_DIR 默认 ~/notes/retro）')
    ap.add_argument('--include-retro', action='store_true', help='不排除复盘会话（默认丢掉发起复盘之后的记录：它们引用的例子会被重复计数）')
    a = ap.parse_args()
    since = dt.datetime.fromisoformat(a.since).timestamp()
    until = dt.datetime.fromisoformat(a.until).timestamp() if a.until else dt.datetime.now().timestamp()
    A = Acc(); W = (since, until)
    claude = os.path.expanduser(os.environ.get('CLAUDE_CONFIG_DIR') or '~/.claude')
    codex = os.path.expanduser(os.environ.get('CODEX_HOME') or '~/.codex')
    files = {'claude': glob.glob(glob.escape(claude) + '/projects/*/*.jsonl'),
             'codex': glob.glob(glob.escape(codex) + '/sessions/**/*.jsonl', recursive=True)}
    for k in files:
        fs = [f for f in files[k] if os.path.getmtime(f) >= since]  # 窗口开始之后被写过的才可能有窗口内的记录
        files[k] = []
        for f in fs:
            cut = None if a.include_retro else retro_start(f)
            if cut is not None:
                A.excluded.append((os.path.basename(f)[:8] if k == 'claude' else os.path.basename(f)[-18:-6]) + '@' + dt.datetime.fromtimestamp(cut).strftime('%m-%d %H:%M'))
                if cut <= since: continue
            files[k].append((f, cut if cut is not None else float('inf')))
    scan_claude(files['claude'], A, W); scan_codex(files['codex'], A, W)
    cov = {k: {'sessions': len(v['sessions']), 'branches': sorted(v['branches'])} for k, v in sorted(A.C.items(), key=lambda kv: -len(kv[1]['sessions']))}
    sess = {s for v in A.C.values() for s in v['sessions']}
    counts = {k: A.B[k]['count'] for k in KEYS}; tc = max(A.M['tool_calls'], 1); ut = max(A.M['user_turns'], 1)
    metrics = {
        'metrics_version': METRICS_VERSION, 'since': a.since,
        'until': a.until or dt.datetime.fromtimestamp(until).strftime('%Y-%m-%dT%H:%M'),
        'sessions': {'claude': sum(s.startswith('cl:') for s in sess), 'codex': sum(s.startswith('cx:') for s in sess)},
        'excluded_retro_sessions': sorted(A.excluded), 'user_turns': A.M['user_turns'], 'tool_calls': A.M['tool_calls'], **counts,
        'rates': {  # 跨周比较用比率：工具类按每千次工具调用，对话类按每百条用户消息
            **{k + '_per_1k_tools': round(counts[k] * 1000 / tc, 1) for k in ('self_correction', 'help_lookup', 'denied', 'tool_error')},
            **{k + '_per_100_turns': round(counts[k] * 100 / ut, 1) for k in ('intervention_correction', 'intervention_observability', 'empty_confirm')}},
        'help': {'sessions': len(A.help_sess), 'sessions_loaded_cheatsheet': len(A.help_sess & A.sheet_sess), 'top': A.help_cmd.most_common(15)},
        'skill_usage': dict(A.skills.most_common()), 'error_kinds': dict(A.errk.most_common()),
        'hook_hits': hook_hits(W), 'flows': A.F.report(), 'coverage': cov,
    }
    if a.out is None:
        year, week, _ = dt.datetime.fromtimestamp(until).isocalendar()
        a.out = os.path.join(RETRO_DIR, f'{year}-W{week:02d}')
    os.umask(0o077)
    os.makedirs(a.out, exist_ok=True)
    json.dump(metrics, open(os.path.join(a.out, 'metrics.json'), 'w'), ensure_ascii=False, indent=2)
    with open(os.path.join(a.out, 'turns.tsv'), 'w') as w:
        for ts, kind, src, tag, t in sorted(A.turns):
            w.write(f"{dt.datetime.fromtimestamp(ts).strftime('%m-%d %H:%M')}\t{kind}\t{src}\t{tag}\t{t}\n")
    with open(os.path.join(a.out, 'samples.md'), 'w') as w:
        w.write(f"# 扫描样本 {a.since} ~ {metrics['until']}\n\n```json\n{json.dumps({k: v for k, v in metrics.items() if k != 'coverage'}, ensure_ascii=False, indent=2)}\n```\n")
        for k in KEYS:
            w.write(f"\n## {k}（{counts[k]}）\n\n" + '\n'.join('- ' + s for s in spread(A.B[k]['samples'])) + '\n')
        w.write('\n## 高频高成本流程（实例数 × 平均步数，不看成败）\n\n| 领域 | 实例 | 会话 | 总步 | 均步 | 最大 | 分钟 | help | 专用工具采用率 | 常见签名 |\n|---|---|---|---|---|---|---|---|---|---|\n')
        for r in metrics['flows']['top']:
            w.write(f"| {r['domain']} | {r['instances']} | {r['sessions']} | {r['steps']} | {r['mean_steps']} | {r['max_steps']} | {r['minutes']} | {r['help']} | {'-' if r['tool_share'] is None else r['tool_share']} | {'; '.join(f'{s}×{n}' for s, n in r['top_sigs'])} |\n")
        w.write('\n最费步的一次（看完整轨迹用 turn.py）：\n\n' + '\n'.join(f"- {r['domain']}〔{r['example']['src']}〕{r['example']['user']} → {' / '.join(r['example']['seq'])}" for r in metrics['flows']['top'][:6]) + '\n')
        w.write('\n跨 ≥3 个会话反复出现的 ID / 坐标（每次都要重新查或手写）：\n\n' + '\n'.join(f'- {k}：{n} 个会话 {c} 次，{t}' for k, n, c, t in metrics['flows']['repeated_entities']) + '\n')
        w.write(f"\n临时手写的带鉴权请求包装脚本：{metrics['flows']['adhoc_wrappers']}\n")
    brief = {k: v for k, v in metrics.items() if k not in ('coverage', 'flows')}
    brief['flows_top'] = [(r['domain'], r['instances'], r['mean_steps'], r['tool_share']) for r in metrics['flows']['top'][:8]]
    brief['covered_projects'] = len(cov)
    print(json.dumps(brief, ensure_ascii=False))

if __name__ == '__main__':
    main()
