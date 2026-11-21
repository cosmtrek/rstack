# rstack

两个让 coding agent「越用越准」的技能，加上配套的 hook。从一套日常在用的个人技能里抽出来，只留框架和思路。

| 技能 | 一句话 | 解决什么问题 |
|---|---|---|
| [`claude-lead`](skills/claude-lead/SKILL.md) | Claude 当主管，codex 当执行者 | 主会话上下文最贵，却把大量时间花在翻文件、跑测试上 |
| [`weekly-retro`](skills/weekly-retro/SKILL.md) | 每周复盘会话记录，把 agent 的错误变成环境资产 | 同样的错这周纠正了，下周换个会话还会再犯 |

两者是一个闭环：claude-lead 每次派发都记账；weekly-retro 每周扫描所有会话、在失败拐点归因，产出的补丁（hook、脚本、技能、约定）
反过来改进包括 claude-lead 在内的整个环境。

## claude-lead：Claude 当主管，codex 当执行者

<p align="center"><img src="docs/claude-lead.svg" alt="claude-lead 设计框架：Claude 主会话判断、写契约、复核、交付，codex 侦察和施工，每轮记账、复盘、调整；契约分七栏" width="100%"></p>

- **委派省的是缓存读**：主会话的开销大头不是输出，而是上下文越大、轮数越多就越贵的缓存读。所以要移出去的是读文件和调试的轮次。
- **执行者看清楚，主管想清楚**：流水线是「侦察 → 拍板 → 施工」，实现只在想清楚之后才派。
- **返工几乎都是契约的锅**：最常见的是范围画窄。契约按栏写，每栏语义固定；没核实过的规则写成待核假设，不写成硬不变量。
- **按时机触发，hook 兜底**：技能描述写「什么任务、什么时刻该派」，不指望模型事先估出工作量；连续只读太多时 hook 再提醒一次。

设计取舍和每条规则的来由见 [DESIGN.md](skills/claude-lead/DESIGN.md)。

## weekly-retro：把 agent 的错误变成环境资产

<p align="center"><img src="docs/weekly-retro.svg" alt="weekly-retro 设计框架：八步每周复盘循环，失败点经拐点四问卡分诊到感知、动作、反馈三层，动态补丁优先，并用一组跨期比率指标观测" width="100%"></p>

- **怪环境，不怪模型**：结论要落到「那一刻缺了什么信号、多了什么噪音、哪个工具误导了它」。
- **介入即失败**：用户纠正或追问进度，都说明环境有缺陷；拍板、补需求不算。
- **只做有复利的修补，先看轨迹再动手**；能做成 hook、脚本的不写成文档。
- **补丁要能验收**：每条配一道只读回放题，全新会话、不给提示，看能否自己做对。
- **复盘本身也被复盘**：每两期看一次介入率、改动有效率、动静比、hook 误拦率和采纳率。

方法论和踩过的坑见 [DESIGN.md](skills/weekly-retro/DESIGN.md)。

## 安装

需要 [Claude Code](https://docs.claude.com/en/docs/claude-code)、已登录的 [Codex CLI](https://github.com/openai/codex)、Python 3.9+、Bash 和 Git。
派发还需要 GNU coreutils 的 `timeout` 或 `gtimeout`（macOS：`brew install coreutils`）。

```bash
bash install.sh            # 软链技能，已有同名技能时跳过
bash install.sh --hooks    # 可选：把 hook 合并进 Claude Code 设置，先备份
```

- 默认装到 `~/.claude/skills` 和 `~/.codex/skills`，遵循 `CLAUDE_CONFIG_DIR`、`CODEX_HOME`；`SKILL_DIRS` 可指定其他目录（换行分隔）。
- 把 [`global/AGENTS.example.md`](global/AGENTS.example.md) 里需要的规则合并进你的全局约定（Claude Code 读 `CLAUDE.md`，Codex 读 `AGENTS.md`），然后新开会话。
- 扫描开箱可用。要定制常用 CLI 或流程领域，把 [`config.example.json`](skills/weekly-retro/config.example.json) 复制到 `$RETRO_DIR/config.json`。

常用环境变量：

| 变量 | 作用 | 默认 |
|---|---|---|
| `MODEL` / `EFFORT` / `SERVICE_TIER` | dispatch.sh 用的 codex 模型、推理强度、服务档 | codex 配置 / medium / codex 默认 |
| `TIMEOUT` | 单次派发超时（秒） | 1800 |
| `DELEGATE_WRITABLE` | 派发时长期放行的可写目录（CLI 登录态、构建缓存） | 无 |
| `NUDGE_THRESHOLD` | 委派提醒阈值（连续只读次数） | 25 |
| `RETRO_DIR` | 复盘记录目录 | `~/notes/retro` |
| `RETRO_CONFIG` | scan.py 配置文件 | `$RETRO_DIR/config.json` |
| `REPLAY_MODEL` | 回放和裁判用的模型 | codex 默认 |

## 上手

1. 在 Claude Code 里调用 `/claude-lead`，挑一个只需读文件的任务走一次派发，复核后用 `ledger.py note` 记账。
2. 调用 `/weekly-retro`。首期看最近七天：先确认扫描覆盖范围，再从 `turns.tsv` 挑出需要修补的失败点。
3. 用合成题试跑回放，确认 Codex 能被调起：

   ```bash
   python3 -I skills/weekly-retro/scripts/replay.py --example --out "$(mktemp -d)"
   ```

4. 之后每周复盘一次，每条采纳的补丁在 `$RETRO_DIR/replays/` 写一道回放题。

## 本地数据与隐私

数据都留在本机，不进仓库：

- **weekly-retro** 扫描本机所有项目的 Claude Code 和 Codex 会话，报告、台账和回放题写在 `$RETRO_DIR`。报告可能含消息原文、命令、路径和环境标识；
  复盘、回放和裁判用的模型会看到相应的样本、题面和回答。分享前先脱敏。
- **claude-lead** 的派发产物（契约、输出、工作区差异）在 `~/.local/share/agent-delegate/runs/`，台账在 `~/.local/state/agent-delegate/`。
- **hook** 的命中日志在 `~/.local/state/agent-hooks/`，只记规则、决定、会话标识等统计字段，不存命令原文。
- 仓库里的 `ledger/` 和 `replays/examples/` 只是模板，自己的记录放 `$RETRO_DIR`。

## 目录

```
skills/
  claude-lead/
    SKILL.md                 判断依据和边界
    DESIGN.md                每条规则的来由
    references/              契约模板、固定约束信封、汇报格式
    scripts/dispatch.sh      派发：拼工作区快照 + 契约 + 固定约束，后台跑 codex，自动记账
    scripts/ledger.py        台账：note / stats / efficiency / list
    scripts/timing.py        派发时机与结果、委派提醒阈值回放
    ledger/retro.md          委派复盘记录模板
  weekly-retro/
    SKILL.md                 八步流程
    DESIGN.md                方法论和踩过的坑
    config.example.json      扫描配置示例（常用 CLI、流程领域表）
    references/tune.md       评估复盘本身
    scripts/scan.py          扫描会话，产出指标、样本、turns.tsv
    scripts/turn.py          看一次介入之前那一回合的轨迹
    scripts/replay.py        反事实重放 + 模型裁判
    scripts/tune_due.py      判断这期要不要评估复盘本身
    replays/examples/        回放题格式示例
    ledger/                  改动台账、调整记录模板
hooks/
  pretool_guard.py           PreToolUse 守卫（示例规则，带自测）
  posttool_delegate_nudge.py 连续只读 N 次注入委派提醒
  install_hooks.py           合并进 Claude Code 设置
global/AGENTS.example.md     配合两个技能的全局约定示例
docs/                        README 里的设计框架图，由 gen_diagrams.py 生成
install.sh                   软链安装，不覆盖已有的同名技能
```

技能里的规则是从一个具体环境里长出来的。搬到你的环境后，**按你自己的台账改**，别当成定律。
