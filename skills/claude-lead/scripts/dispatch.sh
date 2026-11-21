#!/usr/bin/env bash
# 把契约派给 codex 执行。必须用 Bash run_in_background 调用，不自己写等待循环；结束时打印 task / run 并自动记台账。
#
# 新派：dispatch.sh <workdir> <brief.md> <结论|代码> <标签>
# 续派：RESUME=<task_id | run 目录> dispatch.sh - <brief.md>     # brief 只写增量（变了什么 / 返工意见）
# 返工开新会话：TASK=<原 task_id> dispatch.sh <workdir> <brief.md> <结论|代码> <标签>   # 记到原任务下
#
#   交付物「结论」：侦察、排查、盘点、跑测试；工作区出现改动会告警。
#   交付物「代码」：施工。
#   模型默认用 codex 自己的配置（~/.codex/config.toml）；要固定就设 MODEL。两种交付物相同。
#   权限只有一档：可写工作区 + 联网 + auto 审批（越出沙箱的请求由 codex 自动审核）。对外写操作靠信封红线约束。
#
# 环境变量：STAGE=侦察|施工（默认按交付物推断）；ORIGIN=user|me（用户点名派发填 user，默认 me）；
#   MODEL / EFFORT（默认 medium）/ TIMEOUT（秒，默认 1800）/ ADD_DIRS="dir1 dir2" 额外可写目录；
#   SERVICE_TIER（不设就用 codex 默认档）；APPROVAL=user 关掉 auto 审批。
#   DELEGATE_WRITABLE="dir1 dir2"：长期放行的可写目录（CLI 登录态、构建缓存等），建议写进 shell 配置。
# 脚本写在 main 函数里：bash 先读完整个函数再执行，运行中改本文件不会让正在跑的派发崩溃。
set -uo pipefail
umask 077

main() {
  local DG; DG=$(cd "$(dirname "$0")" && pwd)
  local timeout_cmd dep
  timeout_cmd=$(command -v timeout || command -v gtimeout) || {
    echo "缺少 timeout：macOS 请运行 brew install coreutils，Linux 请安装 coreutils。" >&2
    return 127
  }
  for dep in codex git python3; do
    command -v "$dep" >/dev/null || { echo "缺少命令：${dep}，请先安装并确认它在 PATH 里。" >&2; return 127; }
  done
  local STATE="$HOME/.local/state/agent-delegate" RUNS="$HOME/.local/share/agent-delegate/runs"
  local wd brief deliver label task thread="" prev=""
  # codex 沙箱默认只读家目录。构建缓存、CLI 登录态（读凭证并在刷新时回写）只读时会报
  # read-only / token storage is not writable，按需放行；只放存在的目录，不替你创建。
  local caches=() c
  for c in "$HOME/.cache/go-build" "$HOME/.cache/golangci-lint" ${DELEGATE_WRITABLE:-}; do
    [[ -d $c ]] && caches+=("$c")
  done
  # fnm 每个 shell 在这里建 node 软链，只读时 node / npm 脚本直接失败（实测）。
  [[ -d $HOME/.local/state/fnm_multishells ]] && caches+=("$HOME/.local/state/fnm_multishells")
  mkdir -p "$STATE" "$RUNS" || return 1

  if [[ -n ${RESUME:-} ]]; then
    brief=${2:?续派用法: RESUME=<task_id|run目录> dispatch.sh - <brief.md>}
    # 找到这个任务最近一次派发：接受 task_id 或 run 目录（路径 / 目录名）。
    if [[ -d $RESUME ]]; then prev=$(cd "$RESUME" && pwd)
    elif [[ -d $RUNS/$RESUME ]]; then prev="$RUNS/$RESUME"
    else
      prev=$(grep -Flx -- "task=$RESUME" "$RUNS"/*/meta 2>/dev/null | sort | tail -1)
      prev=${prev%/meta}
    fi
    [[ -n $prev && -f $prev/meta ]] || { echo "续派失败：找不到任务或 run「${RESUME}」" >&2; exit 2; }
    thread=$(sed -n 's/^thread=//p' "$prev/meta")
    [[ $thread =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] \
      || { echo "续派失败：$prev 里没有合法的 codex 会话 id（thread=${thread}），不能续派，请新派" >&2; exit 2; }
    task=$(sed -n 's/^task=//p' "$prev/meta"); wd=$(sed -n 's/^workdir=//p' "$prev/meta")
    deliver=$(sed -n 's/^deliver=//p' "$prev/meta"); label=$(sed -n 's/^label=//p' "$prev/meta")
    STAGE=${STAGE:-$(sed -n 's/^stage=//p' "$prev/meta")}; ORIGIN=${ORIGIN:-$(sed -n 's/^origin=//p' "$prev/meta")}
    MODEL=${MODEL:-$(sed -n 's/^model=//p' "$prev/meta" | grep -vx default)}
  else
    wd=$(cd "${1:?用法: dispatch.sh <workdir> <brief.md> <结论|代码> <标签>}" && pwd) || return 2
    brief=${2:?缺 brief}; deliver=${3:?缺交付物（结论|代码）}; label=${4:?缺标签}
    task=${TASK:-"$(date +%m%d)-$label"}
    if [[ -n ${TASK:-} ]] && ! grep -Fqx -- "task=$TASK" "$RUNS"/*/meta 2>/dev/null; then
      echo "TASK=$TASK 没有派发记录，返工要沿用已有任务的 task_id" >&2; exit 2
    fi
  fi
  [[ -f $brief ]] || { echo "brief 不存在: $brief" >&2; exit 2; }
  # worktree 的 git 元数据在主仓 .git/worktrees/<名> 下、不在工作区里：git add / status 写 index.lock 会报只读（实测）。
  # 只放行本 worktree 自己的 gitdir，不放行整个主仓 .git。
  local gd; gd=$(git -C "$wd" rev-parse --absolute-git-dir 2>/dev/null || true)
  [[ -n $gd && $gd != "$wd"/* ]] && caches+=("$gd")
  # 产物目录由本脚本固定（见下方 prompt「不写 /tmp」）；brief 再指定 /tmp 写入位置，codex 会因约束冲突停下
  local tmpw; tmpw=$(grep -nE '/tmp/' "$brief" | grep -E '写|放|存|输出|产物|临时' | grep -vE '(取消|不写|不放|不要|别写|别放|只读)[^，。；;,]{0,8}/tmp/' || true)
  [[ -n $tmpw ]] && { printf '派发拒绝：brief 指定了 /tmp 作为写入位置，和固定约束「产物一律写本次 run 目录」冲突：\n%s\n删掉这几行即可，产物目录会自动写进 prompt；只是读取 /tmp 下的输入文件不受影响。\n' "$tmpw" >&2; exit 2; }
  case $deliver in 结论|代码) ;; *) echo "交付物只能是 结论 或 代码" >&2; exit 2 ;; esac
  if [[ -z $label || $label == */* || $label == *$'\n'* ]]; then
    echo "标签不能为空，也不能包含斜杠或换行。" >&2
    return 2
  fi
  local stage=${STAGE:-}; [[ -z $stage ]] && { [[ $deliver == 代码 ]] && stage=施工 || stage=侦察; }
  local origin=${ORIGIN:-me}
  local model=${MODEL:-} effort=${EFFORT:-medium} to=${TIMEOUT:-1800}

  local base="$RUNS/$(date +%Y%m%d-%H%M%S)-codex-$label"
  local rounds; rounds=$(grep -Flx -- "task=$task" "$RUNS"/*/meta 2>/dev/null | wc -l)
  local run="$base"
  while :; do
    (( rounds > 0 )) && run="$base-r$(( rounds + 1 ))"
    if mkdir "$run" 2>/dev/null; then break; fi
    [[ -d $run ]] || { echo "无法创建产物目录：$run" >&2; return 1; }
    (( rounds += 1 ))
  done
  cp "$brief" "$run/brief.md" || return 1

  # 基线：不提交，靠 HEAD + status + diff 记录派发前状态，复核和回滚都以它为准。
  local branch="" head="" st=""
  if git -C "$wd" rev-parse --verify -q HEAD >/dev/null 2>&1; then
    git -C "$wd" rev-parse HEAD > "$run/base.head"
    git -C "$wd" status --porcelain > "$run/base.status"
    git -C "$wd" diff HEAD > "$run/base.diff"
    branch=$(git -C "$wd" branch --show-current); head=$(git -C "$wd" log -1 --format='%h %s')
    st=$(git -C "$wd" status --short | head -30)
  fi

  # 信封：派发时刻的工作区快照 + 我写的契约 + 固定约束与汇报格式。
  {
    if [[ -n $prev ]]; then
      echo "# 续派（任务 ${task}）"; echo
      echo "下面是自上次以来的变化或返工意见；原任务契约与约束仍然有效。"
    else
      echo "# 任务 ${task}（交付物：$deliver · 阶段：${stage}）"
    fi
    echo
    echo "## 派发时的工作区快照（脚本自动采集，以此为准）"; echo
    echo "- 工作目录：$wd"
    [[ -n $branch$head ]] && echo "- 分支：${branch:-（游离 HEAD）}；HEAD：$head"
    if [[ -n $st ]]; then echo "- 未提交改动："; echo '```'; echo "$st"; echo '```'; else echo "- 工作区干净"; fi
    echo "- 本次产物目录：${run}（中间结果、报告、脚本一律写在这里，不写 /tmp）"
    echo; echo "---"; echo
    cat "$brief"
    if [[ -z $prev ]]; then
      echo; echo "---"; echo
      cat "$DG/../references/envelope.md"
      echo
      if [[ $deliver == 代码 ]]; then cat "$DG/../references/report-code.md"; else cat "$DG/../references/report-result.md"; fi
    fi
  } > "$run/prompt.md"

  local net=true cmd
  cmd=(codex exec --skip-git-repo-check -c "model_reasoning_effort=\"$effort\""
       -c "approvals_reviewer=\"${APPROVAL:-auto_review}\"" -c "sandbox_workspace_write.network_access=$net")
  [[ -n $model ]] && cmd+=(-m "$model")
  [[ -n ${SERVICE_TIER:-} ]] && cmd+=(-c "service_tier=\"$SERVICE_TIER\"")
  if [[ -n $prev ]]; then
    # resume 不接受 -s / -C / --add-dir，也不沿用首派的放行（实测）：用 -c 显式给沙箱和可写目录，并在工作区里启动。
    local roots="\"$wd\",\"$RUNS\"" c d
    for c in ${caches[@]+"${caches[@]}"} ${ADD_DIRS:-}; do roots+=",\"$c\""; done
    cmd=(codex exec resume "${cmd[@]:2}" -c 'sandbox_mode="workspace-write"'
         -c "sandbox_workspace_write.writable_roots=[$roots]" --json -o "$run/final.md" "$thread" -)
  else
    # 放行整个 runs/：resume 不接受 --add-dir，续派的 -rN 产物目录靠首派时的放行才可写。
    cmd+=(-s workspace-write -C "$wd" --add-dir "$RUNS")
    local c; for c in ${caches[@]+"${caches[@]}"}; do cmd+=(--add-dir "$c"); done
    local d; for d in ${ADD_DIRS:-}; do cmd+=(--add-dir "$d"); done
    cmd+=(--json -o "$run/final.md" -)
  fi

  local start rc attempt; start=$(date +%s)
  for attempt in 1 2; do
    (cd "$wd" && "$timeout_cmd" "$to" "${cmd[@]}") < "$run/prompt.md" > "$run/events.jsonl" 2> "$run/stderr.log"
    rc=$?
    # 模型容量报错（很快退出、无产出）自动重试一次。
    if [[ $rc -ne 0 && $attempt -eq 1 ]] && grep -qiE 'capacity|overloaded' "$run/stderr.log" "$run/events.jsonl" 2>/dev/null; then
      echo "容量报错，30 秒后重试一次" >&2; sleep 30; continue
    fi
    break
  done
  local secs=$(( $(date +%s) - start ))

  local diffstat="" warn=""
  if [[ -f $run/base.head ]]; then
    git -C "$wd" diff "$(cat "$run/base.head")" > "$run/after.diff"
    git -C "$wd" status --porcelain > "$run/after.status"
    if ! cmp -s "$run/base.status" "$run/after.status" || ! git -C "$wd" diff HEAD | cmp -s - "$run/base.diff"; then
      diffstat=$(git -C "$wd" diff --shortstat "$(cat "$run/base.head")" | sed 's/^ *//')
      [[ -z $diffstat ]] && diffstat="工作区有变化（见 after.status）"
      [[ $deliver == 结论 ]] && warn="交付物是结论却改动了工作区（${diffstat}）" && echo "警告：$warn" >&2
    fi
  fi

  local new_thread
  new_thread=$(grep -m1 -o '"thread_id":"[^"]*"' "$run/events.jsonl" 2>/dev/null | cut -d'"' -f4)
  [[ -n $prev && -n $new_thread && $new_thread != "$thread" ]] && warn="${warn:+${warn}；}续派开了新会话 ${new_thread}（原 ${thread}）" && echo "警告：续派没接上原会话" >&2
  cat > "$run/meta" <<EOF
task=$task
stage=$stage
deliver=$deliver
origin=$origin
model=${model:-default}
effort=$effort
approval=${APPROVAL:-auto_review}
tier=${SERVICE_TIER:-default}
workdir=$wd
label=$label
exit=$rc
secs=$secs
thread=${new_thread:-$thread}
resume_of=${prev:+$(basename "$prev")}
diffstat=$diffstat
warn=$warn
EOF
  python3 "$DG/ledger.py" auto "$run" || echo "台账自动记录失败（不影响产物）" >&2
  echo "task=$task exit=$rc secs=$secs run=$run"
  if (( rc != 0 )); then
    echo "派发失败（退出码 ${rc}），详见 $run/stderr.log" >&2
  fi
  return "$rc"
}

main "$@"; exit $?
