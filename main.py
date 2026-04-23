# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "openai>=2.32.0",
# ]
# ///

import subprocess
import sys
import json
from pathlib import Path
from openai import OpenAI

CONFIG_PATH = Path.home() / ".autocommit.json"

SYSTEM_PROMPT = """You are a git commit message generator that strictly follows Conventional Commits.

Output format (one line only):
  <type>: <message>

Rules:
- type: feat, fix, refactor, chore, docs, test, style, perf, ci
- message: short, imperative, lowercase, no period
- Output ONLY the commit message, nothing else
"""


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text("{}")

    config = json.loads(CONFIG_PATH.read_text())
    envs = config.get("env", {})

    if not envs:
        print("No configuration found. Let's set one up.\n")
        name = input("Config name [default]: ").strip() or "default"
        url = input("API URL: ").strip()
        key = input("API Key: ").strip()
        model = input("Model: ").strip()

        envs[name] = {"url": url, "key": key, "model": model}
        config["env"] = envs
        CONFIG_PATH.write_text(json.dumps(config, indent=2))
        print(f"\nConfig '{name}' saved to {CONFIG_PATH}\n")

    return config


def get_env(config: dict, name: str | None) -> dict:
    envs = config["env"]
    if name:
        if name not in envs:
            print(f"Config '{name}' not found.", file=sys.stderr)
            sys.exit(1)
        return envs[name]
    return next(iter(envs.values()))


def has_commits() -> bool:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True
    ).returncode == 0


def get_git_diff() -> str:
    staged = subprocess.run(
        ["git", "diff", "--staged"],
        capture_output=True, text=True
    ).stdout.strip()
    if staged:
        return staged

    unstaged = subprocess.run(
        ["git", "diff"],
        capture_output=True, text=True
    ).stdout.strip()
    if unstaged:
        return unstaged

    return subprocess.run(
        ["git", "status", "--short"],
        capture_output=True, text=True
    ).stdout.strip()


def generate_commit_message(env: dict, diff: str | None = None, initial: bool = False) -> str:
    if initial:
        user_content = "This is the very first commit of a brand new repository. Generate a conventional commit message for initializing the project."
    else:
        user_content = f"Diff:\n{diff}"

    client = OpenAI(base_url=env["url"], api_key=env["key"])
    response = client.chat.completions.create(
        model=env["model"],
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content.strip()


def cmd_run(env: dict):
    if not has_commits():
        message = generate_commit_message(env, initial=True)
    else:
        diff = get_git_diff()
        if not diff:
            print("No changes detected.", file=sys.stderr)
            sys.exit(1)
        message = generate_commit_message(env, diff=diff)

    suffix = input("Any issue ID or note for the () suffix? (leave blank to skip): ").strip()
    if suffix:
        message = f"{message} ({suffix})"

    print(f"\n{message}\n")
    confirm = input("Commit? [Y/n]: ").strip().lower()
    if confirm in ("n", "no"):
        print("Aborted.", file=sys.stderr)
        sys.exit(0)

    result = subprocess.run(["git", "commit", "-m", message])
    sys.exit(result.returncode)


def cmd_test(env: dict):
    print(f"Testing config: url={env['url']} model={env['model']}")
    client = OpenAI(base_url=env["url"], api_key=env["key"])
    response = client.chat.completions.create(
        model=env["model"],
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=16,
    )
    print(f"Response: {response.choices[0].message.content.strip()}")


def main():
    argv = sys.argv[1:]

    if argv and argv[-1] in ("run", "test"):
        command = argv[-1]
        env_name = argv[0] if len(argv) == 2 else None
    else:
        command = "run"
        env_name = argv[0] if argv else None

    config = load_config()
    env = get_env(config, env_name)

    if command == "run":
        cmd_run(env)
    else:
        cmd_test(env)


if __name__ == "__main__":
    main()
