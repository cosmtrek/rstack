"""Antigravity（agy）会话记录的只读解析，scan.py 和 turn.py 共用。

脚本用 `python3 -I` 运行，同目录模块不在 sys.path 里，调用方按文件路径加载本模块。
布局：<brain>/<conversationId>/.system_generated/logs/transcript_full.jsonl（没有就用 transcript.jsonl），
每行一个步骤（USER_INPUT / PLANNER_RESPONSE / 各类工具结果……）；<brain> 的上一层有 conversation_summaries.db
（SQLite），记着每个会话的 workspace_uris 和 nesting_depth（> 0 是子代理会话）。
brain 目录：默认 ${GEMINI_HOME:-~/.gemini}/*/brain，再加 AGY_BRAIN_DIRS（冒号分隔）和配置里的 agy_brain_dirs，
都支持 ~ 和通配符，按真实路径去重。
"""
import datetime as dt
import glob
import json
import os
import re
import sqlite3
import urllib.parse

TRANSCRIPTS = ('transcript_full.jsonl', 'transcript.jsonl')
NON_RESULT = {'USER_INPUT', 'PLANNER_RESPONSE', 'SYSTEM_MESSAGE', 'CHECKPOINT'}
# 宿主（agy 本身、T3 Code 等）给用户消息套的外壳；只留用户真正说的话
WRAPPERS = re.compile(r'<(t3_code_instructions|runtime_info|t3_context|pull_request_linking|assistant_citations|'
                      r'ADDITIONAL_METADATA|USER_SETTINGS_CHANGE|SYSTEM_MESSAGE)\b[^>]*>.*?</\1>', re.S)
STAMPS = re.compile(r'^(?:Created|Completed) At: .*(?:\n|$)', re.M)
EXIT = re.compile(r'\bexited with code (-?\d+)')
PATH_ARGS = ('Path', 'AbsolutePath', 'absolute_path', 'TargetFile')


def _expand(specs):
    out = []
    for p in specs:
        p = os.path.expanduser(os.path.expandvars(p))
        out += sorted(glob.glob(p)) if glob.has_magic(p) else [p]
    return out


def brain_dirs(extra=()):
    gem = os.path.expanduser(os.environ.get('GEMINI_HOME') or '~/.gemini')
    cands = sorted(glob.glob(glob.escape(gem) + '/*/brain'))
    cands += _expand(x for x in (os.environ.get('AGY_BRAIN_DIRS') or '').split(':') if x)
    cands += _expand(extra)
    seen, out = set(), []
    for p in cands:
        r = os.path.realpath(p)
        if os.path.isdir(p) and r not in seen:
            seen.add(r)
            out.append(p)
    return out


def config_dirs(cfg):
    """配置里的 agy_brain_dirs：字符串或字符串列表。格式不对返回 None，由调用方决定报错还是忽略。"""
    v = cfg.get('agy_brain_dirs') or []
    v = [v] if isinstance(v, str) else v
    return v if isinstance(v, list) and all(isinstance(x, str) for x in v) else None


def summaries(brain):
    """conversation_id → {'workspaces': [路径…], 'depth': nesting_depth}。数据库缺失或读不了就返回 {}。"""
    db = os.path.join(os.path.dirname(os.path.abspath(brain)), 'conversation_summaries.db')
    if not os.path.isfile(db):
        return {}
    uri = 'file:' + urllib.parse.quote(db)
    rows = None
    for mode in ('?mode=ro', '?mode=ro&immutable=1'):  # 后者用于目录不可写、WAL 读不了的情况
        try:
            con = sqlite3.connect(uri + mode, uri=True, timeout=2)
            try:
                rows = con.execute('SELECT conversation_id, workspace_uris, nesting_depth FROM conversation_summaries').fetchall()
            finally:
                con.close()
            break
        except sqlite3.Error:
            continue
    out = {}
    for cid, uris, depth in rows or []:
        try:
            ws = [urllib.parse.unquote(urllib.parse.urlparse(u).path) for u in json.loads(uris or '[]') if isinstance(u, str)]
        except (TypeError, ValueError):
            ws = []
        out[cid] = {'workspaces': [w for w in ws if w], 'depth': depth if isinstance(depth, int) else 0}
    return out


def conversations(brain):
    """(conversationId, transcript 路径)。"""
    try:
        names = sorted(os.listdir(brain))
    except OSError:
        return
    for cid in names:
        logs = os.path.join(brain, cid, '.system_generated', 'logs')
        for t in TRANSCRIPTS:
            p = os.path.join(logs, t)
            if os.path.isfile(p):
                yield cid, p
                break


def ts(d):
    t = d.get('created_at')
    if not isinstance(t, str):
        return None
    try:
        return dt.datetime.fromisoformat(t.replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def user_text(content):
    """剥掉 <USER_REQUEST>、<user_request> 和宿主注入的说明块。"""
    if not isinstance(content, str):
        return ''
    c = content
    m = re.search(r'<USER_REQUEST>(.*)</USER_REQUEST>', c, re.S) or re.search(r'<USER_REQUEST>(.*)', c, re.S)
    if m:
        c = m.group(1)
    m = re.search(r'<user_request>(.*)</user_request>', c, re.S)
    if m:
        c = m.group(1)
    return WRAPPERS.sub('', c).strip()


def steps(path):
    """按顺序产出 (kind, 时间戳, 内容, 附加)：
    ('user', x, 文本, None) 仅 source=USER_EXPLICIT；('text', x, 回复, None)；('call', x, 工具名, 参数)；
    ('result', x, 原始步骤, 对应的 tool_call 或 None)。结果按顺序配对上一条 PLANNER_RESPONSE 的 tool_calls。"""
    pending = []
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            t, x = d.get('type'), ts(d)
            if t == 'USER_INPUT':
                pending = []
                if d.get('source') == 'USER_EXPLICIT':
                    yield 'user', x, user_text(d.get('content')), None
            elif t == 'PLANNER_RESPONSE':
                calls = [c for c in d.get('tool_calls') or [] if isinstance(c, dict)]
                pending = list(calls)
                if isinstance(d.get('content'), str) and d['content'].strip():
                    yield 'text', x, d['content'], None
                for c in calls:
                    yield 'call', x, c.get('name') or '?', c.get('args') if isinstance(c.get('args'), dict) else {}
            elif t and t not in NON_RESULT:
                yield 'result', x, d, (pending.pop(0) if pending else None)


def command(name, args):
    return args.get('CommandLine') if name == 'run_command' and isinstance(args.get('CommandLine'), str) else None


def file_path(args):
    return next((args[k] for k in PATH_ARGS if isinstance(args.get(k), str)), None)


def result_error(d, call):
    """工具结果报错就返回报错文本，否则 None。报错 = status=ERROR、ERROR_MESSAGE 步骤，或命令退出码非零。"""
    content = d.get('content') if isinstance(d.get('content'), str) else ''
    body = STAMPS.sub('', content).strip()
    code = d.get('exit_code')
    if not isinstance(code, int) and (d.get('type') == 'RUN_COMMAND' or (call or {}).get('name') == 'run_command'):
        m = EXIT.search(body[:400])
        code = int(m.group(1)) if m else None
    bad_exit = isinstance(code, int) and code != 0
    if not (d.get('status') == 'ERROR' or d.get('type') == 'ERROR_MESSAGE' or bad_exit):
        return None
    err = d.get('error') if isinstance(d.get('error'), str) else ''
    txt = err or body
    return f'Exit code {code} {txt}' if bad_exit and not err else txt
