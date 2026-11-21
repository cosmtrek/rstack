# Claude Code hook

- `pretool_guard.py`：PreToolUse(Bash) 守卫，命中已知的高代价误操作时拦下或要求确认，并带上修复提示。
- `posttool_delegate_nudge.py`：PostToolUse 委派提醒，只注入提示、不拦截。
- `install_hooks.py`：幂等地把两者合并进 `~/.claude/settings.json`，不动已有的其他 hook，改之前自动备份。

只有 Claude Code 执行 hook；Codex 等其他 agent 靠全局约定和前置检查脚本。能做成脚本的优先做脚本。

## 守卫规则怎么写

- **默认 ask，确定会失败才 deny。** deny 的提示里写清怎么做才对（修复提示），并说明豁免方式。
- **豁免**：命令末尾加 `# confirmed-by-user` 视为用户已确认，直接放行并记日志。agent 只能在用户明确同意后加。
- **匹配写窄**：只在命令执行位置匹配（行首、`;` `&&` `|` 之后，可带 `timeout` / `env` 前缀），heredoc 正文不参与匹配。
- **出错放行**：脚本任何异常都 exit 0；settings 里 timeout 5 秒。
- **上线前回放**：新增或修改规则后，拿最近一周 transcript 里的全部 Bash 命令回放一遍，确认只命中该拦的。
- **只放用户级**：不改仓库或插件的 hook；个人 hook 不抢别人的拒绝权。
- **记日志**：每次命中写 `~/.local/state/agent-hooks/hits.jsonl`（rule / decision / session / selftest，不保存命令原文和工作目录）。weekly-retro 统计命中次数、
  豁免比例（≈误拦率）、连续零命中；误拦高就改，长期零命中就删。
- **自测**：每条规则带一个 `selftest` 命令（用 `false &&` 短路、带 `# retro-selftest` 标记），weekly-retro 每期用 Bash 工具跑一次，
  期望被拦并写日志；扫描时记为 `<rule>:selftest`，不算真实命中。
- **来源**：每条规则在下表记一行来源（哪一期复盘、什么问题），方便以后判断还要不要留。

| id | 决策 | 拦什么 | 来源 |
|---|---|---|---|
| force-push-main | ask | `git push --force` 到 main / master（示例） | 示例 |
| prod-config-cli | deny | 用 CLI 改 prod 配置（示例，一定被管控拒绝） | 示例 |

## 委派提醒（delegate-nudge）

主会话从上次派发或写操作（改文件、git commit/push）起连续 N 次只读调用（默认 25，`NUDGE_THRESHOLD` 可调），注入一次「委派提醒」，
之后每满 N 次再提醒；提醒只指向全局委派约定，不点名执行方；子代理不提醒。

- 为什么需要它：委派判断写在技能里，但模型经常只加载了某个专项技能（比如排查类），委派判断根本没被读到；用 hook 在「已经读了很多」
  的那一刻兜底。
- 阈值怎么调：`skills/claude-lead/scripts/timing.py` 用历史会话复算提醒点，看不同阈值能覆盖多少「读了很多却没派」的会话、
  提醒后有没有派、派出去的结果如何。
- 计数存 `~/.local/state/agent-hooks/nudge/<session>`。自测：`--selftest` 加 `NUDGE_STATE=<临时目录>`，喂 N 次 Read 期望第 N 次输出提醒。
