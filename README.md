# autocommit

A CLI tool that generates [Conventional Commits](https://www.conventionalcommits.org/) messages from your git diff using an OpenAI-compatible API.

## Usage

```bash
alias autocommit='uv run https://raw.githubusercontent.com/chronolai/autocommit/refs/heads/master/main.py'
autocommit                    # generate a commit message using the default config
autocommit run -n             # skip the issue ID suffix prompt
autocommit -e work run        # use the "work" config
autocommit test               # ping the default config to verify connectivity
autocommit -e work test       # ping the "work" config
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

If the repository has no commits yet, autocommit skips the diff and asks the model to generate an initial commit message directly.

## Options

- `-e`, `--env <name>`: select a named config (default: first entry in `~/.autocommit.json`)
- `run -n`, `run --no-suffix`: skip the issue ID suffix prompt and commit directly

## Commit format

```
<type>: <message> (<suffix>)
```

- `type`: `feat`, `fix`, `refactor`, `chore`, `docs`, `test`, `style`, `perf`, `ci`
- `message`: short, imperative, lowercase, no period
- `suffix`: optional — issue ID or note, prompted interactively

## Dev

```bash
uv sync
uv run main.py                 # run locally
uv run main.py run -n          # skip the suffix prompt
uv run main.py -e work run     # use the "work" config
uv run main.py test            # ping the default config
```