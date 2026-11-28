#!/usr/bin/env bash
# 把本仓库的技能软链进 Claude Code / Codex / Antigravity（agy）的技能目录，初始化私有目录 $RSTACK_HOME，并（可选）安装 hook。
# 不覆盖已存在的同名技能：目标已存在就跳过并提示，避免冲掉你正在用的版本。
#
#   bash install.sh                # 链接技能 + 初始化 $RSTACK_HOME + 给本仓库装提交前脱敏检查
#   bash install.sh --hooks        # 同时把 Claude Code hook 合并进 ~/.claude/settings.json（会先备份）
#
# 目录：claude-lead 依赖 Claude Code 主会话，只装到 Claude（$CLAUDE_SKILL_DIR，默认 ${CLAUDE_CONFIG_DIR:-~/.claude}/skills）；
# 其余技能同时装到 Codex（$CODEX_SKILL_DIR，默认 ${CODEX_HOME:-~/.codex}/skills）；
# agy 只装 AGY_SKILLS 里列的（目前是 weekly-retro，$AGY_SKILL_DIR，默认 ${GEMINI_HOME:-~/.gemini}/config/skills）。
# 把某个变量设为空字符串就跳过那一边。
# 私有目录：$RSTACK_HOME（默认 ~/.rstack）下的 config/、retro/、state/delegate/、state/hooks/，权限 700。
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
case ${1:-} in
  ""|--hooks) ;;
  *) echo "用法：bash install.sh [--hooks]" >&2; exit 2 ;;
esac
CLAUDE_DIR=${CLAUDE_SKILL_DIR-"${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills"}
CODEX_DIR=${CODEX_SKILL_DIR-"${CODEX_HOME:-$HOME/.codex}/skills"}
AGY_DIR=${AGY_SKILL_DIR-"${GEMINI_HOME:-$HOME/.gemini}/config/skills"}
CLAUDE_ONLY=" claude-lead "
AGY_SKILLS=" weekly-retro "   # agy 支持矩阵见 README「支持的 harness」；新技能验证过再加进来

link() {  # link <目标目录> <技能源目录>
  local d=$1 s=${2%/} dst
  dst="$1/$(basename "$s")"
  if [[ -e $dst || -L $dst ]]; then
    if [[ $dst -ef $s ]]; then echo "已链接：$dst"
    else echo "跳过：$dst 已存在；要换成本仓库的版本请先自行移走"; fi
    return
  fi
  ln -s "$s" "$dst"
  echo "链接：$dst -> $s"
}

for s in "$ROOT"/skills/*/; do
  name=$(basename "$s")
  if [[ -n $AGY_DIR && $AGY_SKILLS == *" $name "* ]]; then mkdir -p "$AGY_DIR"; link "$AGY_DIR" "$s"; fi
  if [[ -n $CLAUDE_DIR ]]; then mkdir -p "$CLAUDE_DIR"; link "$CLAUDE_DIR" "$s"; fi
  [[ -n $CODEX_DIR ]] || continue
  if [[ $CLAUDE_ONLY == *" $name "* ]]; then
    # 旧版 install.sh 也链到了 Codex；只清理指向本仓库的那条软链，别的不动
    old="$CODEX_DIR/$name"
    if [[ -L $old && $old -ef ${s%/} ]]; then rm "$old"; echo "移除：$old（$name 只装到 Claude）"; fi
    continue
  fi
  mkdir -p "$CODEX_DIR"; link "$CODEX_DIR" "$s"
done

# 私有覆盖层：环境相关的配置、复盘产物、运行日志都放这里，不进仓库。
RH=${RSTACK_HOME:-$HOME/.rstack}
for d in "$RH" "$RH/config" "$RH/retro" "$RH/state" "$RH/state/delegate" "$RH/state/hooks"; do
  mkdir -p "$d"; chmod 700 "$d"
done
echo "私有目录：$RH（config/ retro/ state/delegate/ state/hooks/，权限 700）"

# 本仓库是公开的：在自己的 clone 里装提交前脱敏检查。已有别的 pre-commit 时不覆盖，只提示。
if git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  (cd "$ROOT" && bash scripts/check_public.sh --install-hook) || true
fi

if [[ ${1:-} == --hooks ]]; then
  python3 "$ROOT/hooks/install_hooks.py"
fi
echo "完成。私有配置示例：skills/weekly-retro/config.example.json → $RH/config/retro.json，"
echo "  hooks/guard_rules.example.json → $RH/config/guard_rules.json；详见 README「公开与私有」。"
