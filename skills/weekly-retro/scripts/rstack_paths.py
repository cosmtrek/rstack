"""weekly-retro 脚本共用的路径约定和「不写进公开仓库」护栏。

脚本用 `python3 -I` 运行，同目录模块不在 sys.path 里，调用方按文件路径加载本模块。
- RSTACK_HOME：私有根目录，默认 ~/.rstack；config/ 放配置，retro/ 放复盘产物，state/ 放运行日志。
- RETRO_DIR：复盘目录，默认 $RSTACK_HOME/retro。
"""
import os
import re
import subprocess
import sys

RSTACK_HOME = os.path.expanduser(os.environ.get('RSTACK_HOME') or '~/.rstack')
RETRO_DIR = os.path.expanduser(os.environ.get('RETRO_DIR') or os.path.join(RSTACK_HOME, 'retro'))
CONFIG_DIR = os.path.join(RSTACK_HOME, 'config')
STATE_DIR = os.path.join(RSTACK_HOME, 'state')
REMOTE = re.compile(r'[/:]rstack(?:\.git)?/?$')


def git_root(path):
    """向上找含 .git（目录或 worktree 的 .git 文件）的目录；不在仓库里返回 None。"""
    p = os.path.realpath(path)
    while True:
        if os.path.exists(os.path.join(p, '.git')):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


def is_rstack_repo(root):
    """本脚本所在的仓库、同结构的副本，或远端名为 rstack 的仓库都算。"""
    here = git_root(os.path.dirname(os.path.realpath(__file__)))
    if here and os.path.realpath(root) == here:
        return True
    if os.path.isfile(os.path.join(root, 'skills', 'weekly-retro', 'scripts', 'scan.py')) \
            and os.path.isdir(os.path.join(root, 'skills', 'claude-lead')):
        return True
    try:
        out = subprocess.run(['git', '-C', root, 'config', '--get-regexp', r'^remote\..*\.url$'],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return any(REMOTE.search(line.split(None, 1)[-1].strip()) for line in out.splitlines() if line.strip())


def refuse_repo_out(path):
    """输出目录落在 rstack 仓库里就报错退出：复盘产物含会话原文、命令和环境标识，不能进公开仓库。"""
    root = git_root(path)
    if root and is_rstack_repo(root):
        sys.exit(f'拒绝写入：输出目录 {os.path.realpath(path)} 在 rstack 仓库（{root}）里。复盘产物含会话原文和环境标识，'
                 f'只能写私有目录。去掉 --out 用默认的 $RSTACK_HOME/retro，或指定仓库外的目录。')
