# Git Workflow Rules

## Golden Rules — Non-Negotiable

- **Never commit directly to `main`**
- **Never push directly to `main`**
- **Never merge directly into `main`**
- All work starts from `dev`
- All PRs target `dev`, not `main`

---

## Branch Naming

| Type | Pattern | Example |
|---|---|---|
| New feature | `feature/<name>` | `feature/mpesa-webhook-auth` |
| Bug fix | `fix/<name>` | `fix/payment-double-processing` |
| Chore / config | `chore/<name>` | `chore/update-dependencies` |
| Hotfix (urgent) | `hotfix/<name>` | `hotfix/rotate-at-api-key` |

Use kebab-case. Keep names short but descriptive.

---

## Workflow — Every Time, No Exceptions

### 1. Sync dev before creating your branch

```bash
git checkout dev
git pull origin dev
```

### 2. Create your feature branch off dev

```bash
git checkout -b feature/<name>
# e.g. git checkout -b fix/payment-reference-unique-constraint
```

### 3. Do your work — commit as you go

```bash
git add <files>
git commit -m "feat: add unique constraint on Payment.reference"
```

Use [Conventional Commits](https://www.conventionalcommits.org/):
- `feat:` — new feature
- `fix:` — bug fix
- `chore:` — tooling, config, dependencies
- `docs:` — documentation only
- `refactor:` — code change with no behaviour change
- `test:` — adding or updating tests

### 4. Before pushing — sync with dev again (avoid conflicts)

```bash
git fetch origin
git rebase origin/dev
# resolve any conflicts, then:
git rebase --continue
```

### 5. Push your feature branch

```bash
git push origin feature/<name>
```

### 6. Open a Pull Request → targeting `dev`

- Go to GitHub → Pull Requests → New Pull Request
- **Base:** `dev` ← **Compare:** `feature/<name>`
- Add a clear title and description of what changed and why
- Do **not** merge — leave it open for review

---

## Branch Flow Diagram

```
main          ←── (only merged from dev via reviewed PR)
  │
dev           ←── (all feature PRs merge here)
  │
feature/<name>   ←── (your work happens here)
```

---

## What Happens After the PR

- PR is reviewed and approved
- Merged into `dev` (squash or merge commit)
- `dev` is periodically merged into `main` via a release PR — **not your job unless you own the release**

---

## Quick Reference Cheatsheet

```bash
# Start new work
git checkout dev
git pull origin dev
git checkout -b feature/my-change

# Save progress
git add .
git commit -m "feat: describe what you did"

# Stay in sync with dev
git fetch origin
git rebase origin/dev

# Ship it
git push origin feature/my-change
# → open PR on GitHub targeting dev
```
