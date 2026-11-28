#!/usr/bin/env bash
# 提交前脱敏检查：本仓库是公开的，环境相关的规则、正则、事例只该写进 $RSTACK_HOME（默认 ~/.rstack）。
#
#   scripts/check_public.sh                 # 检查暂存区内容（pre-commit hook 用这个），等同 --staged
#   scripts/check_public.sh --all           # 检查已跟踪和未被忽略的新文件的工作区内容
#   scripts/check_public.sh <文件>...        # 检查指定文件
#   scripts/check_public.sh --install-hook  # 装成本仓库的 git pre-commit hook（install.sh 会自动装）
#
# 拦什么：本机绝对路径（家目录、数据盘、root 家目录）、IPv4、邮箱、UUID、64 位及以上十六进制串（安装 hash、sha256、令牌）、
# 常见密钥前缀、当前用户名和主机名、
# $RSTACK_HOME/config/denylist.txt 里的自定义敏感词（一行一个，# 开头是注释，按字面、不分大小写匹配），
# 以及私有文件名（retro.json、guard_rules.json、*.local.* 等）。
# 误报：在那一行加上 check-public:ignore 豁免；豁免会留在 diff 里，审阅时能看到。
set -uo pipefail

ROOT=$(git rev-parse --show-toplevel 2>/dev/null || true)  # 检查指定文件时可以不在仓库里
need_repo() { [[ -n $ROOT ]] || { echo "check_public：$1 要在 git 仓库里运行" >&2; exit 2; }; }
RSTACK_HOME=${RSTACK_HOME:-$HOME/.rstack}
DENYLIST="$RSTACK_HOME/config/denylist.txt"
MARK='check-public:ignore'

install_hook() {
  local dir hook
  dir=$(cd "$ROOT" && git rev-parse --git-path hooks) || return 2
  [[ $dir == /* ]] || dir="$ROOT/$dir"
  hook="$dir/pre-commit"
  mkdir -p "$dir"
  if [[ -e $hook ]] && ! grep -q 'rstack:check_public' "$hook"; then
    echo "跳过：$hook 已存在且不是本脚本装的；要启用请在里面加一行：\"\$(git rev-parse --show-toplevel)/scripts/check_public.sh\" --staged" >&2
    return 1
  fi
  cat > "$hook" <<'EOF'
#!/usr/bin/env bash
# rstack:check_public —— 提交前脱敏检查，由 scripts/check_public.sh --install-hook 安装
exec "$(git rev-parse --show-toplevel)/scripts/check_public.sh" --staged
EOF
  chmod +x "$hook"
  echo "已安装 pre-commit hook：$hook"
}

# ---- 规则：标签、匹配（ERE）、放行（ERE，作用于匹配到的片段）----
B='(^|[^A-Za-z0-9_])'
RE_PATH='(^|[^A-Za-z0-9_.~$-])/(Users|home|root|data)/[^[:space:]"'"'"'`)<>]*'
RE_IPV4='(^|[^0-9.])[0-9]{1,3}(\.[0-9]{1,3}){3}([^0-9.]|$)'
ALLOW_IPV4='^(127\.|0\.0\.0\.0$|255\.255\.255\.255$|192\.0\.2\.|198\.51\.100\.|203\.0\.113\.)'
RE_EMAIL='[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}'
ALLOW_EMAIL='^(git@(github|gitlab)\.com|noreply@.*|.*@users\.noreply\.github\.com|.*@example\.(com|org|net))$'
RE_UUID='[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
ALLOW_UUID='^0{8}-0{4}-0{4}-0{4}-0{12}$'
# 64 位及以上的十六进制串：宿主按安装生成的目录 hash（如 providers/<hash>/）、sha256、令牌。示例里用通配符代替
RE_HEX64='[0-9a-fA-F]{64,}'
ALLOW_HEX64='^0+$'
RE_SECRET="${B}(sk-(ant-|proj-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}|(AKIA|ASIA)[0-9A-Z]{16}|xox[abposr]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35}|glpat-[A-Za-z0-9_-]{20,})|-----BEGIN [A-Z ]*PRIVATE KEY-----"
PRIVATE_NAME='(^|/)(retro\.json|guard_rules\.json|denylist\.txt|config\.json|metrics\.jsonl?|turns\.tsv|samples\.md|summary\.json|hits\.jsonl|records\.jsonl)$|\.local\.[^/]*$'

# 用户名和主机名：常见词（root、admin、ubuntu……）只在「用户@主机」里算，避免把普通英文词当成泄露；其他按独立边界、不分大小写匹配。
COMMON='^(root|admin|administrator|user|ubuntu|debian|centos|fedora|ec2-user|runner|vagrant|pi|git|test|guest|dev|developer|docker|node|nobody|www-data|localhost|server|host|vps|box|devbox|default|container|macbook|macbook-pro|mac)$'
esc() { printf '%s' "$1" | sed 's/[][\.*^$+?(){}|/]/\\&/g'; }
USER_NAME=${USER:-$(id -un 2>/dev/null || true)}
HOST_FULL=$(hostname 2>/dev/null || true); HOST_SHORT=${HOST_FULL%%.*}
RE_IDENT=""
add_ident() {
  local v=$1 lc
  lc=$(printf '%s' "$v" | tr '[:upper:]' '[:lower:]')
  [[ -n $v && ${#v} -ge 3 ]] || return 0
  [[ $lc =~ $COMMON ]] && return 0
  RE_IDENT+="${RE_IDENT:+|}$(esc "$v")"
}
add_ident "$USER_NAME"; add_ident "$HOST_SHORT"; [[ $HOST_FULL != "$HOST_SHORT" ]] && add_ident "$HOST_FULL"
[[ -n $RE_IDENT ]] && RE_IDENT="${B}(${RE_IDENT})([^A-Za-z0-9_]|$)"
RE_USERHOST=""
[[ -n $USER_NAME && -n $HOST_SHORT ]] && RE_USERHOST="${B}$(esc "$USER_NAME")@$(esc "$HOST_SHORT")"

TMP=$(mktemp -d "${TMPDIR:-/tmp}/check_public.XXXXXX") || exit 2
trap 'rm -rf "$TMP"' EXIT
DENY=""
if [[ -f $DENYLIST ]]; then
  grep -vE '^[[:space:]]*(#|$)' "$DENYLIST" | sed 's/[[:space:]]*$//' > "$TMP/deny" || true
  [[ -s $TMP/deny ]] && DENY="$TMP/deny"
fi

HITS=0
report() { HITS=$((HITS + 1)); printf '%s:%s: [%s] %s\n' "$1" "$2" "$3" "${4:0:120}"; }

ipv4_ok() {  # 放行段或不是合法地址（如版本号 300.1.1.1）
  local ip=$1 o
  [[ $ip =~ $ALLOW_IPV4 ]] && return 0
  local IFS=.
  for o in $ip; do (( 10#$o > 255 )) && return 0; done
  return 1
}

# scan <显示名> <内容文件> <标签> <ERE> [放行 ERE] [-i]
scan() {
  local name=$1 file=$2 label=$3 re=$4 allow=${5:-} flags=-noE hit n m
  [[ ${6:-} == -i ]] && flags=-noiE
  while IFS= read -r hit; do
    n=${hit%%:*}; m=${hit#*:}
    [[ " $EXEMPT " == *" $n "* ]] && continue
    if [[ $label == ipv4 ]]; then
      m=$(printf '%s' "$m" | grep -oE '[0-9]{1,3}(\.[0-9]{1,3}){3}')
      ipv4_ok "$m" && continue
    fi
    [[ -n $allow && $m =~ $allow ]] && continue
    report "$name" "$n" "$label" "$m"
  done < <(grep $flags -- "$re" "$file" 2>/dev/null)
}

check_content() {
  local name=$1 file=$2 hit n
  [[ $name =~ $PRIVATE_NAME ]] && report "$name" 0 "private-file" "私有文件名，应放 \$RSTACK_HOME 而不是仓库"
  grep -Iq '' "$file" 2>/dev/null || return 0   # 二进制或空文件
  EXEMPT=$(grep -nF -- "$MARK" "$file" | cut -d: -f1 | tr '\n' ' ')
  scan "$name" "$file" abs-path "$RE_PATH"
  scan "$name" "$file" ipv4 "$RE_IPV4"
  scan "$name" "$file" email "$RE_EMAIL" "$ALLOW_EMAIL"
  scan "$name" "$file" uuid "$RE_UUID" "$ALLOW_UUID"
  scan "$name" "$file" hex64 "$RE_HEX64" "$ALLOW_HEX64"
  scan "$name" "$file" secret "$RE_SECRET"
  [[ -n $RE_IDENT ]] && scan "$name" "$file" user/host "$RE_IDENT" "" -i
  [[ -n $RE_USERHOST ]] && scan "$name" "$file" user@host "$RE_USERHOST" "" -i
  if [[ -n $DENY ]]; then
    while IFS= read -r hit; do
      n=${hit%%:*}
      [[ " $EXEMPT " == *" $n "* ]] && continue
      report "$name" "$n" denylist "${hit#*:}"
    done < <(grep -noiF -f "$DENY" -- "$file" 2>/dev/null)
  fi
}

mode=staged
case ${1:-} in
  --install-hook) need_repo --install-hook; install_hook; exit $? ;;
  ""|--staged) mode=staged ;;
  --all) mode=all ;;
  -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
  -*) echo "未知参数：$1" >&2; exit 2 ;;
  *) mode=files ;;
esac

count=0
case $mode in
  staged)
    need_repo --staged; cd "$ROOT" || exit 2
    while IFS= read -r -d '' f; do
      git show ":$f" > "$TMP/blob" 2>/dev/null || continue
      check_content "$f" "$TMP/blob"; count=$((count + 1))
    done < <(git diff --cached --name-only --diff-filter=ACMR -z)
    ;;
  all)
    need_repo --all; cd "$ROOT" || exit 2
    while IFS= read -r -d '' f; do
      [[ -f $f ]] || continue
      check_content "$f" "$f"; count=$((count + 1))
    done < <(git ls-files -z --cached --others --exclude-standard)
    ;;
  files)
    for f in "$@"; do
      [[ -f $f ]] || { echo "不存在：$f" >&2; HITS=$((HITS + 1)); continue; }
      check_content "$f" "$f"; count=$((count + 1))
    done
    ;;
esac

if (( HITS > 0 )); then
  echo "check_public：发现 ${HITS} 处疑似敏感内容（已检查 ${count} 个文件）。环境相关的内容移到 \$RSTACK_HOME；确属误报的行加 ${MARK}。" >&2
  exit 1
fi
echo "check_public：通过（已检查 ${count} 个文件）"
