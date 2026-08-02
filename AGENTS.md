# AGENTS.md — KS agent operating notes

## Always use git worktrees

**Mandatory for agents:** Do all feature/bug implementation in an isolated git worktree under `.worktrees/`. Do not land feature commits on the primary repo checkout.

1. Create a branch + worktree first (`git worktree add -b <branch> .worktrees/<dir> <base>`), or use the Cursor/native worktree tool.
2. One topic per worktree (e.g. hero-levels ≠ inventory UI shell).
3. `.worktrees/` is gitignored — never commit worktree contents.
4. Follow the Superpowers `using-git-worktrees` skill at the start of implementation work.
5. Cursor rule: `.cursor/rules/always-use-worktrees.mdc` (alwaysApply).

## Other standing rules

- ADB-first for BlueStacks / KingShot device actions (`.cursor/rules/adb-first.mdc`).
- Specs/plans live under `docs/superpowers/`; clarify before large refactors.
- Prefer small cohesive modules under `ks/`; config in `config/` YAML.
