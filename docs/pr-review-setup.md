# PR Review Command — Setup Guide

This guide covers installing and configuring the prerequisites for the `/pr-review` Claude Code command.

## Prerequisites

| Tool | Purpose |
|------|---------|
| `gh` | GitHub CLI — fetches PR metadata, diffs, posts comments |
| `jq` | JSON processor — parses Jira API responses |
| Jira credentials | `JIRA_INSTANCE`, `JIRA_USERNAME`, `JIRA_API_TOKEN` in `env/.env` |

---

## 1. Install `gh` (GitHub CLI)

### Ubuntu / Debian

```bash
# Add the official GitHub CLI repository
(type -p wget >/dev/null || sudo apt-get install wget -y) \
  && sudo mkdir -p -m 755 /etc/apt/keyrings \
  && out=$(mktemp) \
  && wget -nv -O "$out" https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  && cat "$out" | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
  && sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
  && sudo apt update \
  && sudo apt install gh -y
```

### macOS (Homebrew)

```bash
brew install gh
```

### Conda / Mamba

```bash
conda install -c conda-forge gh
```

### Verify installation

```bash
gh --version
```

---

## 2. Authenticate `gh`

### Interactive login (recommended)

```bash
gh auth login
```

Follow the prompts:
1. Select **GitHub.com** (or GitHub Enterprise if applicable)
2. Choose your preferred protocol: **HTTPS** (recommended) or SSH
3. Authenticate via **browser** (opens a device-code flow) or paste a **personal access token**

### Token-based login (non-interactive / CI)

```bash
# Using a Personal Access Token (classic) or Fine-Grained Token
export GH_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
gh auth login --with-token <<< "$GH_TOKEN"
```

Required token scopes for `/pr-review`:
- `repo` — read PR data, post comments
- `read:org` — for private org repos

### Verify authentication

```bash
gh auth status
```

Expected output:

```
github.com
  ✓ Logged in to github.com account <username>
  ✓ Git operations protocol: https
  ✓ Token: ghp_****
  ✓ Token scopes: 'repo', 'read:org'
```

---

## 3. Install `jq`

### Ubuntu / Debian

```bash
sudo apt-get install jq -y
```

### macOS (Homebrew)

```bash
brew install jq
```

### Verify installation

```bash
jq --version
```

---

## 4. Configure Jira Credentials

The `/pr-review` command reads Jira credentials from `env/.env`, loaded at runtime via `navconfig`.

### Required variables

Add these to your `env/.env` file under a `[Jira]` section:

```ini
[Jira]
JIRA_INSTANCE=https://trocglobal.atlassian.net/
JIRA_USERNAME=your-email@example.com
JIRA_API_TOKEN=your-jira-api-token
```

### How to generate a Jira API Token

1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click **Create API token**
3. Give it a label (e.g., `claude-pr-review`)
4. Copy the generated token and paste it as `JIRA_API_TOKEN` in `env/.env`

### Verify Jira access

```bash
# Quick test (replace values or load from env/.env first)
source .venv/bin/activate
python -c "
from navconfig import config
import os, urllib.request, base64

instance = os.environ['JIRA_INSTANCE'].rstrip('/')
user = os.environ['JIRA_USERNAME']
token = os.environ['JIRA_API_TOKEN']
creds = base64.b64encode(f'{user}:{token}'.encode()).decode()

req = urllib.request.Request(
    f'{instance}/rest/api/3/myself',
    headers={'Authorization': f'Basic {creds}', 'Content-Type': 'application/json'}
)
resp = urllib.request.urlopen(req)
print(f'Authenticated as: {resp.read().decode()[:200]}')
"
```

---

## 5. Usage

Once all prerequisites are in place:

```
/pr-review <PR_URL> <JIRA_KEY> [--auto-draft]
```

### Examples

```
/pr-review https://github.com/Trocdigital/navigator-dataintegrator-tasks/pull/4028 NAV-8036
/pr-review https://github.com/Trocdigital/navigator-dataintegrator-tasks/pull/4028 NAV-8036 --auto-draft
```

### What it does

1. Fetches PR metadata, description, and diff from GitHub
2. Fetches Jira ticket description and acceptance criteria
3. Reviews the PR against each acceptance criterion
4. Generates a structured compliance report
5. Optionally posts the review as a PR comment
6. Optionally converts the PR to draft if criteria are not met (`--auto-draft`)

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `gh: command not found` | Install `gh` (see section 1) |
| `gh CLI not authenticated` | Run `gh auth login` (see section 2) |
| `jq: command not found` | Install `jq` (see section 3) |
| `JIRA_INSTANCE not set` | Add to `env/.env` and ensure navconfig loads it |
| `401 Unauthorized` from Jira | Check `JIRA_API_TOKEN` is valid and not expired |
| Double-slash in Jira URL | The command strips trailing slashes automatically |
