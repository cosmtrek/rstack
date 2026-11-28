#!/usr/bin/env python3
"""用全新的只读 Codex 会话运行 $RETRO_DIR/replays/*.json，并按预期结论判分。

RETRO_DIR 默认 $RSTACK_HOME/retro（RSTACK_HOME 默认 ~/.rstack）。--out 不能指向 rstack 仓库内。
"""
import argparse
import concurrent.futures
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location('rstack_paths', Path(__file__).resolve().parent / 'rstack_paths.py')
paths = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(paths)
RETRO_DIR = Path(paths.RETRO_DIR)
PREFIX = ('这是一道只读回放题。只读取作答所需的材料，禁止修改文件、提交推送、调用写接口或发消息。'
          '可以按全局约定使用已安装的技能。用一段话给出结论和依据。\n\n')


def ask(cwd, model, effort, output, prompt, timeout):
    cmd = ['codex', '-a', 'never', 'exec', '--skip-git-repo-check', '--ephemeral',
           '-C', str(cwd), '-s', 'read-only', '-c', 'mcp_servers={}', '-c', 'web_search="disabled"',
           '-c', f'model_reasoning_effort={json.dumps(effort)}']
    if model:
        cmd += ['-m', model]
    cmd += ['-o', str(output), prompt]
    try:
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, timeout=timeout)
        if result.returncode:
            return '', f'Codex 退出码 {result.returncode}，请检查 CLI 版本、登录和模型配置'
        answer = output.read_text(encoding='utf-8').strip()
        return (answer, '') if answer else ('', 'Codex 未返回有效文本')
    except subprocess.TimeoutExpired:
        return '', 'Codex 调用超时'
    except (OSError, UnicodeError):
        return '', '无法启动 Codex 或读取回答'


def judge(q, answer, scratch, model):
    prompt = ('你是判分员，直接根据以下文本判断，不调用工具。'
              '结论一致第一行写 PASS，结论矛盾、关键判断缺失或含糊则写 FAIL；第二行说明理由。\n\n'
              f'【问题】{q["prompt"]}\n【标准结论】{q["expected"]}\n【回答】{answer}')
    result, error = ask(scratch, model, 'low', scratch / 'judge.txt', prompt, 300)
    if error:
        return None, error
    verdict, _, reason = result.partition('\n')
    verdict = verdict.strip()
    if verdict not in ('PASS', 'FAIL'):
        return None, '裁判未返回有效的 PASS 或 FAIL'
    return verdict == 'PASS', reason.strip()[:200]


def run(q, out, model, effort):
    qid = q['id']
    try:
        cwd = Path(q.get('cwd', '~')).expanduser().resolve()
    except (OSError, RuntimeError):
        return {'id': qid, 'pass': None, 'reason': '无法解析题目的 cwd'}
    if not cwd.is_dir():
        return {'id': qid, 'pass': None, 'reason': '题目的 cwd 不存在'}
    with tempfile.TemporaryDirectory(prefix='retro-replay-') as directory:
        scratch = Path(directory)
        answer, error = ask(cwd, model, effort, scratch / 'answer.md', PREFIX + q['prompt'], 900)
        if error:
            return {'id': qid, 'pass': None, 'reason': error}
        (out / f'{qid}.md').write_text(answer + '\n', encoding='utf-8')
        missing = [p for p in q.get('must_contain', []) if not re.search(p, answer)]
        forbidden = [p for p in q.get('must_not_contain', []) if re.search(p, answer)]
        if missing or forbidden:
            verdict, reason = False, '正则检查失败'
        elif q.get('expected'):
            verdict, reason = judge(q, answer, scratch, model)
        else:
            verdict, reason = True, ''
    return {'id': qid, 'pass': verdict, 'judge': reason, 'missing': missing,
            'forbidden': forbidden, 'chars': len(answer), 'note': q.get('note')}


def load_questions(parser):
    questions = []
    ids = set()
    for path in sorted((RETRO_DIR / 'replays').glob('*.json')):
        try:
            q = json.loads(path.read_text(encoding='utf-8'))
            if not re.fullmatch(r'[A-Za-z0-9_-]+', q['id']) or q['id'] in ids:
                raise ValueError('题号无效或重复')
            if not isinstance(q['prompt'], str) or not q['prompt'].strip():
                raise ValueError('缺少有效题目')
            if not isinstance(q.get('cwd', '~'), str):
                raise ValueError('cwd 应为路径字符串')
            for field in ('must_contain', 'must_not_contain'):
                patterns = q.get(field, [])
                if not isinstance(patterns, list):
                    raise ValueError(f'{field} 应为正则列表')
                for pattern in patterns:
                    re.compile(pattern)
        except (OSError, KeyError, TypeError, ValueError, re.error) as exc:
            parser.error(f'{path}: {exc}')
        ids.add(q['id'])
        questions.append(q)
    return questions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='本期目录，回答写到 <out>/replays/；不能在 rstack 仓库内')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--only', help='用逗号分隔的题号')
    selection.add_argument('--example', action='store_true', help='用合成文件冒烟，无需自行建题')
    parser.add_argument('--model', default=os.environ.get('REPLAY_MODEL'))
    parser.add_argument('--effort', default='medium')
    args = parser.parse_args()
    paths.refuse_repo_out(str(args.out.expanduser()))
    os.umask(0o077)
    out = args.out.expanduser().resolve() / 'replays'
    questions = [] if args.example else load_questions(parser)
    if args.only:
        selected = set(args.only.split(','))
        missing = selected - {q['id'] for q in questions}
        if missing:
            parser.error(f'找不到题号 {", ".join(sorted(missing))}。请检查 $RETRO_DIR/replays，或用 --example 试跑。')
        questions = [q for q in questions if q['id'] in selected]
    for q in questions:
        if q.get('paused'):
            print(f"SKIP {q['id']}（paused）：{q['paused']}")
    questions = [q for q in questions if not q.get('paused')]
    if not args.example and not questions:
        print('没有可跑的题。可用 --example 试跑，或在 $RETRO_DIR/replays 添加题目。')
        return 0
    if not shutil.which('codex'):
        parser.error('找不到 codex，请安装并登录 Codex CLI。')

    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='retro-example-') as example_dir:
        if args.example:
            (Path(example_dir) / 'example.txt').write_text('RETRO-SAMPLE-42\n', encoding='utf-8')
            questions = [{'id': 'sample', 'cwd': example_dir, 'prompt': '读取 example.txt，回答文件中的一行。',
                          'must_contain': [r'\bRETRO-SAMPLE-42\b']}]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda q: run(q, out, args.model, args.effort), questions))
    (out / 'summary.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for row in results:
        status = {True: 'PASS', False: 'FAIL', None: 'UNDETERMINED'}[row['pass']]
        print(f'{status} {row["id"]} {row.get("reason") or row.get("judge") or ""}'.rstrip())
    passed = sum(row['pass'] is True for row in results)
    print(f'通过 {passed}/{len(results)}')
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
