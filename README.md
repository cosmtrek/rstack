# rstack

两个让 coding agent「越用越准」的技能，加上配套的 hook。从一套个人日常在用的技能里抽出来，去掉了业务和个人信息，只留框架和思路。

| 技能 | 一句话 | 解决什么问题 |
|---|---|---|
| [`claude-lead`](skills/claude-lead/SKILL.md) | Claude 当主管，codex 当执行者 | 主会话上下文最贵，却把大量时间花在翻文件、跑测试上 |
| [`weekly-retro`](skills/weekly-retro/SKILL.md) | 每周复盘会话记录，把 agent 的错误变成环境资产 | 同样的错这周纠正了，下周换个会话还会再犯 |

两者是一个闭环：claude-lead 每次派发都记账，weekly-retro 每周扫描所有会话、在失败拐点归因，产出的补丁（hook、脚本、技能、约定）
反过来改进包括 claude-lead 在内的整个环境。

## 核心思路

### claude-lead（详见 [DESIGN.md](skills/claude-lead/DESIGN.md)）

<p align="center"><img src="docs/claude-lead.svg" alt="claude-lead 设计框架：Claude 主会话判断、写契约、复核、交付，codex 侦察和施工，每轮记账、复盘、调整；契约分七栏" width="100%"></p>

- 主会话的开销大头是**缓存读**，不是输出：上下文越大、轮数越多越贵。委派省钱的机制是把读文件和调试的轮次移出去。
- 分工：执行者负责**看清楚**，主管负责**想清楚**；实现只在想清楚之后才派。流水线是「侦察 → 拍板 → 施工」。
- 返工几乎都是**契约**的锅：范围画窄、口径未定、事实写错、外部行为没冒烟。契约分「硬不变量 / 行为范围 / 未决口径 / 待核假设 /
  业务风险 / 现场自决 / 已知」几栏，各自有明确的语义。
- 触发靠**时机和任务类型**写进描述，再用 hook 在「连续读了很多」时兜底，而不是指望模型事先估出工作量。
- 每轮复核都记账（通过与否、原因、契约缺口类型、是否手修），复盘时用固定口径看一次通过率、token 分布和派发时机。

### weekly-retro（详见 [DESIGN.md](skills/weekly-retro/DESIGN.md)）

<p align="center"><img src="docs/weekly-retro.svg" alt="weekly-retro 设计框架：八步每周复盘循环，失败点经拐点四问卡分诊到感知、动作、反馈三层，动态补丁优先，并用一组跨期比率指标观测" width="100%"></p>

- **怪环境，不怪模型**：结论必须落到「那一刻缺了什么信号、多了什么噪音、哪个工具误导了它」。
- **介入即失败**：用户纠正或追问进度，都说明环境有缺陷。
- **只做有复利的修补**，**先看轨迹再动手**。
- 分诊成感知层 / 动作层 / 反馈层，**动态补丁优先**（hook、前置检查脚本、封装工具 > 文档、记忆、约定）。
- 每个补丁配一道**只读回放题**：全新无头会话、不给提示，看能否自己做对；模型当裁判初筛，人工复核。
- 每两期**评估一次复盘本身**：介入率有没有降、改动有没有用、动静比、hook 误拦率、采纳率、漏报。

## 目录

```
skills/
  claude-lead/
    SKILL.md                 判断依据和边界
    DESIGN.md                每条规则的来由
    references/              契约模板、固定约束信封、汇报格式
    scripts/dispatch.sh      派发：自动拼工作区快照 + 契约 + 固定约束，后台跑 codex，自动记账
    scripts/ledger.py        台账：note / stats / efficiency / list
    scripts/timing.py        派发时机与结果、委派提醒阈值回放
    ledger/retro.md          你自己的委派复盘记录（模板）
  weekly-retro/
    SKILL.md                 八步流程
    DESIGN.md                方法论和踩过的坑
    config.example.json      环境相关配置（常用 CLI、流程领域表等）
    references/tune.md       评估复盘本身
    scripts/scan.py          扫描 Claude Code / Codex 会话，产出指标、样本、turns.tsv
    scripts/turn.py          看一次介入之前那一回合的轨迹
    scripts/replay.py        反事实重放 + 模型裁判
    scripts/tune_due.py      判断这期要不要评估复盘本身
    replays/                 回放题（examples/ 是格式示例）
    ledger/                  改动台账、调整记录（模板）
hooks/
  pretool_guard.py           PreToolUse 守卫（示例规则，带 selftest）
  posttool_delegate_nudge.py 连续只读 N 次注入委派提醒
  install_hooks.py           合并进 ~/.claude/settings.json
global/AGENTS.example.md     配合这两个技能的全局约定示例
docs/                        README 里的两张设计框架图（SVG），由 gen_diagrams.py 生成
install.sh                   软链安装，不覆盖已存在的同名技能
```

## 安装

需要 [Claude Code](https://docs.claude.com/en/docs/claude-code)、已登录的 [Codex CLI](https://github.com/openai/codex)、Python 3.9+、Bash 和 Git。派发还需要 GNU coreutils 的 `timeout` 或 `gtimeout`。macOS 可运行 `brew install coreutils`，Linux 通常已预装。

从克隆好的仓库目录运行：

```bash
bash install.sh            # 链接技能，已有同名技能时跳过
bash install.sh --hooks    # 可选：安装 Claude Code hook，先备份现有设置
```

默认安装到 `~/.claude/skills` 和 `~/.codex/skills`。设置了 `CLAUDE_CONFIG_DIR` 或 `CODEX_HOME` 时使用对应目录。用 `SKILL_DIRS` 可指定安装位置，多个目录用换行分隔。安装完成后新开会话，将 `global/AGENTS.example.md` 中需要的规则合并到你的全局约定。Claude Code 读取 `CLAUDE.md`，Codex 读取 `AGENTS.md`。

扫描开箱可用。需要定制 CLI 或流程领域时，把 `skills/weekly-retro/config.example.json` 复制到 `$RETRO_DIR/config.json`，或设置 `RETRO_CONFIG` 指向自己的文件。

可调的环境变量：

| 变量 | 作用 | 默认 |
|---|---|---|
| `MODEL` / `EFFORT` / `SERVICE_TIER` | dispatch.sh 用的 codex 模型、推理强度、服务档 | codex 自己的配置 / medium / codex 默认 |
| `DELEGATE_WRITABLE` | 派发时额外放行可写的目录（CLI 登录态、构建缓存） | 无 |
| `NUDGE_THRESHOLD` | 委派提醒阈值 | 25 |
| `RETRO_DIR` | 每期复盘记录目录 | `~/notes/retro` |
| `RETRO_CONFIG` | scan.py 配置文件 | `$RETRO_DIR/config.json` |
| `REPLAY_MODEL` | 回放和裁判用的模型 | codex 默认 |

### 个人数据

- `weekly-retro` 会扫描本机所有项目的 Claude Code 和 Codex 会话。详细报告、个人台账和回放题放在 `$RETRO_DIR`，默认是 `~/notes/retro`。报告可能含消息原文、命令、项目路径和环境标识。复盘模型会看到本次读取的样本，回放模型会收到题面及作答所需的材料，裁判会收到题面、标准结论和回答。分享或提交前请先脱敏。
- `claude-lead` 将派发契约、输出和工作区差异保存到 `~/.local/share/agent-delegate/runs/`，派发台账在 `~/.local/state/agent-delegate/`。Hook 命中日志在 `~/.local/state/agent-hooks/`，新记录只包含规则、结果、会话标识及自测标记等统计字段。旧日志可能仍含命令原文，请留在本机。
- 如果以前把自己的配置、台账或题目写到了技能目录，先移到仓库外，再更新技能；仓库里的 `ledger/` 和 `replays/examples/` 只用于参考。

## 怎么用起来

1. 在 Claude Code 调用 `/claude-lead`，选一个只需读文件的任务走一次派发流程，复核后用 `ledger.py note` 记账。
2. 在 Claude Code 调用 `/weekly-retro`。首期默认看最近七天，先确认覆盖范围，再从 `turns.tsv` 选出需要修补的失败点。装了 Hook 才需要执行 Hook 自测。
3. 在仓库目录用合成题试跑回放。它会调用已登录的 Codex，结果写入临时目录。

   ```bash
   python3 -I skills/weekly-retro/scripts/replay.py --example --out "$(mktemp -d)"
   ```

4. 每条采纳的补丁在个人回放目录写一道题。之后每周复盘一次，隔两期评估复盘本身。

技能里的规则是从一个具体环境里长出来的，搬到你的环境后，**按你自己的台账改**，别当成定律。
