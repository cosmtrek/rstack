#!/usr/bin/env python3
"""查看一次用户介入前的回合，支持 Claude Code 和 Codex。

用法: python3 -I turn.py '<会话标识>|<月-日 时:分>|<关键词>' ...
例: python3 -I turn.py 'cl:1234abcd|01-10 11:34|应该是这个文档'
标识和时间取自 turns.tsv。也接受旧格式的 Claude 会话前缀和「日 时:分」。
输出可能含原始用户消息、模型回复和命令。TAIL / TW / AFTER 可调整截取长度。
"""
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

CLAUDE = Path(os.environ.get('CLAUDE_CONFIG_DIR') or '~/.claude').expanduser()
CODEX = Path(os.environ.get('CODEX_HOME') or '~/.codex').expanduser()
TW = int(os.environ.get('TW', '110'))
TAIL = int(os.environ.get('TAIL', '900'))
AFTER = int(os.environ.get('AFTER', '0'))


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ' '.join(block.get('text', '') for block in content if isinstance(block, dict))
    return ''


def load(sid):
    source, _, key = sid.partition(':')
    if not key:
        source, key = 'cl', source
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', key):
        raise ValueError(f'无效会话标识：{sid}')
    if source == 'cl':
        paths = sorted((CLAUDE / 'projects').glob(f'*/{key}*.jsonl'))
    elif source == 'cx':
        paths = sorted(p for p in (CODEX / 'sessions').rglob('*.jsonl') if p.name[-18:-6] == key)
    else:
        raise ValueError(f'未知会话类型：{source}')
    if len(paths) != 1:
        raise ValueError(f'找不到唯一会话：{sid}（匹配 {len(paths)} 个）')

    events = []
    with paths[0].open(encoding='utf-8', errors='replace') as f:
        for line in f:
            try:
                d = json.loads(line)
                when = dt.datetime.fromisoformat(d['timestamp'].replace('Z', '+00:00')).astimezone()
            except (KeyError, TypeError, ValueError):
                continue
            if source == 'cx':
                if d.get('type') != 'response_item':
                    continue
                p = d.get('payload') or {}
                if p.get('type') == 'message' and p.get('role') in ('user', 'assistant'):
                    events.append((when, p['role'], 'text', text_of(p.get('content'))))
                elif p.get('type') in ('function_call', 'custom_tool_call', 'local_shell_call'):
                    details = p.get('arguments') or p.get('input') or p.get('action') or ''
                    events.append((when, 'assistant', 'tool', f"{p.get('name', p['type'])} {str(details)[:TW]}"))
                continue
            if d.get('isSidechain') or d.get('isMeta'):
                continue
            content = (d.get('message') or {}).get('content')
            role = d.get('type')
            if role in ('user', 'assistant') and (message := text_of(content)):
                events.append((when, role, 'text', message))
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get('type') == 'tool_use':
                    data = block.get('input') or {}
                    detail = data.get('command') or data.get('file_path') or data.get('skill') or data.get('description') or data
                    events.append((when, role, 'tool', f"{block.get('name', '?')} {str(detail)[:TW]}"))
    return events


def one_line(text):
    return text.replace('\t', ' ').replace('\n', ' ⏎ ')


def show(sid, date, key):
    events = load(sid)
    fmt = '%m-%d %H:%M' if '-' in date else '%d %H:%M'
    for i, (when, role, kind, msg) in enumerate(events):
        if (role, kind) != ('user', 'text') or when.strftime(fmt) != date or key not in one_line(msg):
            continue
        prev = next((j for j in range(i - 1, -1, -1)
                     if events[j][1:3] == ('user', 'text') and not events[j][3].startswith('<')), None)
        print(f'\n===== {sid} {date}')
        if prev is not None:
            print(f'上一条用户: {events[prev][3][:200]!r}')
        segment = events[0 if prev is None else prev + 1:i]
        tools = [text for _, _, kind, text in segment if kind == 'tool']
        print(f'  [本回合工具 {len(tools)} 次] 末 6 次:')
        for tool in tools[-6:]:
            print('    ·', one_line(tool))
        replies = [text for _, role, kind, text in segment if (role, kind) == ('assistant', 'text')]
        if replies:
            print('  [agent 末条]', one_line(replies[-1][-TAIL:]))
        print(f'  >>> 用户: {msg[:300]!r}')
        if AFTER > 0:
            remaining = 2
            for _, role, kind, text in events[i + 1:]:
                if (role, kind) == ('user', 'text') and not text.startswith('<'):
                    break
                if (role, kind) == ('assistant', 'text'):
                    print('  [之后 agent]', one_line(text[:AFTER]))
                    remaining -= 1
                    if remaining == 0:
                        break
        return
    raise ValueError(f'未在 {sid} 的 {date} 找到匹配消息')


def main(args):
    if not args or args == ['--help']:
        print(__doc__)
        return 0 if args else 2
    status = 0
    for arg in args:
        try:
            parts = arg.split('|', 2)
            if len(parts) != 3 or not all(parts):
                raise ValueError('参数格式应为：会话标识|月-日 时:分|关键词')
            show(*parts)
        except (OSError, ValueError) as exc:
            print(exc, file=sys.stderr)
            status = 1
    return status


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
