# 回放题

个人题目放在 `$RETRO_DIR/replays/*.json`，默认是 `~/.rstack/retro/replays/`（`$RSTACK_HOME/retro/replays/`），不放进本仓库。这里的 `examples/` 是格式模板，请按自己的环境替换工作目录和题面。首次使用可运行 `scripts/replay.py --example --out <仓库外的目录>`，用合成文件验证 Codex 回放。

必填字段是 `id`（唯一题号）和 `prompt`（题面）。可选字段包括 `cwd`（工作目录，省略时用家目录）、`origin`（来源）、`expected`（交给裁判的标准结论）、`must_contain` / `must_not_contain`（正则列表）、`note`（备注）和 `paused`（停跑原因）。

回放和裁判使用只读 Codex 会话，关闭额外审批、MCP 服务和网页搜索。题面、作答材料、完整回答和标准结论都可能进入模型上下文，写题时先脱敏。通过、失败和未判定分别记为 `true`、`false` 和 `null`，结果保存在输出目录的 `replays/summary.json`。
