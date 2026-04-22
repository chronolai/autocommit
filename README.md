# autocommit

A CLI tool that generates [Conventional Commits](https://www.conventionalcommits.org/) messages from your git diff using an OpenAI-compatible API.

## Usage

```bash
alias autocommit='uv run https://raw.githubusercontent.com/chronolai/autocommit/refs/heads/master/main.py'
autocommit test          # ping "[default]" config to verify connectivity
```

On first run, if `~/.autocommit.json` is missing or empty, you'll be prompted to set up a config:

```
Config name [default]: work
API URL: https://api.openai.com/v1
API Key: your-api-key
Model: gpt-4o
```

Configs are stored in `~/.autocommit.json`:

```json
{
  "env": {
    "work":     { "url": "...", "key": "...", "model": "..." },
    "personal": { "url": "...", "key": "...", "model": "..." }
  }
}
```

Example session:

```
$ git add src/auth.py
$ autocommit
Any issue ID or note for the () suffix? (leave blank to skip): AUTH-123

feat: add user authentication (AUTH-123)

Commit? [Y/n]:
```

Press Enter to commit, or type `n` to abort.
