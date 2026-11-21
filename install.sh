#!/usr/bin/env bash
# 把本仓库的技能软链进 Claude Code / Codex 的技能目录，并（可选）安装 hook。
# 不覆盖已存在的同名技能：目标已存在就跳过并提示，避免冲掉你正在用的版本。
#
#   bash install.sh                # 只链接技能
#   bash install.sh --hooks        # 同时把 hook 合并进 ~/.claude/settings.json（会先备份）
#   SKILL_DIRS="$HOME/.claude/skills" bash install.sh   # 自定义目标目录
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
case ${1:-} in
  ""|--hooks) ;;
  *) echo "用法：bash install.sh [--hooks]" >&2; exit 2 ;;
esac
DIRS=${SKILL_DIRS:-"${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills
${CODEX_HOME:-$HOME/.codex}/skills"}
while IFS= read -r d; do
  [[ -n $d ]] || continue
  mkdir -p "$d"
  for s in "$ROOT"/skills/*/; do
    name=$(basename "$s"); dst="$d/$name"
    if [[ -e $dst || -L $dst ]]; then
      if [[ $dst -ef $s ]]; then echo "已链接：$dst"
      else echo "跳过：$dst 已存在；要换成本仓库的版本请先自行移走"; fi
      continue
    fi
    ln -s "${s%/}" "$dst"
    echo "链接：$dst -> ${s%/}"
  done
done <<< "$DIRS"
if [[ ${1:-} == --hooks ]]; then
  python3 "$ROOT/hooks/install_hooks.py"
fi
echo "完成。weekly-retro 可直接使用，按需参考 README 自定义配置。"
