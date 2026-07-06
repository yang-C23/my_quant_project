# ADR-0004: 原地重构，长期 v2 分支 + 任务短分支 + 里程碑 tag

- 状态：accepted
- 日期：2026-07-06
- 决策人：用户 + 规划者

## Context

v1 仓库包含已验证的 TDX 二进制解析、GBBQ 解密与复权算法，git 历史（含 QFQ 修复 4b51c91、DB 迁移 f132436）是重要的工程记忆。新建仓库会丢失历史并需重新验证数据管线。

## Decision

- `main` 冻结在 v1 终态；全部 v2 工作在长期分支 `v2` 上集成。
- 每张任务卡一个 `task/TASK-XXX-<slug>` 短分支，审查通过后 `--no-ff` 合并回 `v2`。
- 文件移动用纯 `git mv` 独立提交（保 `git log --follow`）。
- 里程碑 gate 通过后打 tag（`v2.0-docs`, `v2.0-m0`…）并 push；v2 何时合回 main 由用户决定。

## Consequences

- 得到：历史与回滚能力、渐进迁移、PG 参照期内新旧共存。
- 承担：一段时间内仓库同时存在 v1 遗留（只读）与 v2 新代码，靠 architecture.md §5 的处置表管理。
