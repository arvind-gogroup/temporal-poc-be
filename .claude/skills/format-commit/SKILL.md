---
name: format-commit
description: Use this skill when the user asks to commit changes, make a commit, or save their work to git.
model: claude-haiku-4-5-20251001
---

When triggered:

1. Run `git add .` to stage all changes
2. Run `git diff --cached` to inspect what's staged
3. Generate a commit message in this exact format:

```
[{prefix}] - {message}

(Impacts)  - {impacts}
```

**prefix** — pick one: `Feature | Fix | Refactor | Doc | Style | Chore | Test | Perf | Build | CI`
**message** — short imperative summary of what changed (≤ 72 chars)
**impacts** — one brief line: possible side-effects or affected areas

Example:
```
[Refactor] - extract auth logic into useAuth hook

(Impacts) - affects login flow and session handling
```

4. Commit using that message via HEREDOC to preserve formatting
5. Run `git status` to confirm success