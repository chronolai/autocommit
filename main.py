# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "openai>=2.32.0",
#   "rich>=13.0.0",
# ]
# ///

import argparse
import itertools
import os
import select
import subprocess
import sys
import json
import termios
import threading
import tty
from pathlib import Path
from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich import print as rprint

CONFIG_PATH = Path.home() / ".autocommit.json"
console = Console()

SYSTEM_PROMPT = """You are a git commit message generator that strictly follows Conventional Commits.

Output format (one line only):
  <type>: <message>

Rules:
- type: feat, fix, refactor, chore, docs, test, style, perf, ci
- message: short, imperative, lowercase, no period
- Output ONLY the commit message, nothing else
"""

COMMIT_TYPE_COLORS = {
    "feat": "bright_green",
    "fix": "bright_red",
    "refactor": "bright_cyan",
    "chore": "yellow",
    "docs": "bright_blue",
    "test": "magenta",
    "style": "bright_magenta",
    "perf": "bright_yellow",
    "ci": "cyan",
}


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text("{}")

    config = json.loads(CONFIG_PATH.read_text())
    envs = config.get("env", {})

    if not envs:
        console.print("\n[yellow]No configuration found. Let's set one up.[/yellow]\n")
        name = Prompt.ask("Config name", default="default")
        url = Prompt.ask("API URL")
        key = Prompt.ask("API Key", password=True)
        model = Prompt.ask("Model")

        envs[name] = {"url": url, "key": key, "model": model}
        config["env"] = envs
        CONFIG_PATH.write_text(json.dumps(config, indent=2))
        console.print(f"\n[green]Config '[bold]{name}[/bold]' saved to {CONFIG_PATH}[/green]\n")

    return config


def get_env(config: dict, name: str | None) -> dict:
    envs = config["env"]
    if name:
        if name not in envs:
            console.print(f"[bold red]Config '{name}' not found.[/bold red]", file=sys.stderr)
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


def has_staged_files() -> bool:
    result = subprocess.run(
        ["git", "diff", "--staged", "--name-only"],
        capture_output=True, text=True
    )
    return bool(result.stdout.strip())


def _generate_with_cancel(env: dict, **kwargs) -> str | None:
    """Run generate_commit_message in a daemon thread. Returns None if ESC pressed."""
    result: list[str | None] = [None]
    exc: list[BaseException | None] = [None]
    done = threading.Event()

    def worker():
        try:
            result[0] = generate_commit_message(env, **kwargs)
        except Exception as e:
            exc[0] = e
        finally:
            done.set()

    threading.Thread(target=worker, daemon=True).start()

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    spinner = itertools.cycle('⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏')
    msg = " Generating commit message... (ESC to abort)"
    try:
        tty.setcbreak(fd)
        while not done.is_set():
            sys.stdout.write(f'\r{next(spinner)}{msg}')
            sys.stdout.flush()
            if select.select([sys.stdin], [], [], 0.1)[0]:
                ch = sys.stdin.read(1)
                if ch == '\x1b':
                    if select.select([sys.stdin], [], [], 0.05)[0]:
                        sys.stdin.read(2)
                        continue
                    sys.stdout.write('\n')
                    sys.stdout.flush()
                    return None
        sys.stdout.write('\r' + ' ' * (len(msg) + 1) + '\r')
        sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

    if exc[0]:
        raise exc[0]
    return result[0]


def _read_line_or_esc(prompt: str) -> str | None:
    """Read a line of input. Returns None if ESC is pressed."""
    console.print(prompt, end="")
    sys.stdout.flush()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    buf = []
    try:
        tty.setcbreak(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch == '\x1b':
                if select.select([sys.stdin], [], [], 0.05)[0]:
                    sys.stdin.read(2)  # drain arrow-key sequence
                    continue
                sys.stdout.write('\n')
                sys.stdout.flush()
                return None
            elif ch in ('\r', '\n'):
                sys.stdout.write('\n')
                sys.stdout.flush()
                return ''.join(buf)
            elif ch in ('\x7f', '\x08'):
                if buf:
                    buf.pop()
                    sys.stdout.write('\b \b')
                    sys.stdout.flush()
            elif ord(ch) >= 32:
                buf.append(ch)
                sys.stdout.write(ch)
                sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _confirm_or_esc(prompt: str) -> bool | None:
    """Single-key confirm. Returns True/False, or None if ESC is pressed."""
    console.print(prompt, end="")
    sys.stdout.flush()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch == '\x1b':
                if select.select([sys.stdin], [], [], 0.05)[0]:
                    sys.stdin.read(2)
                    continue
                sys.stdout.write('\n')
                sys.stdout.flush()
                return None
            elif ch in ('y', 'Y', '\r', '\n'):
                sys.stdout.write('y\n')
                sys.stdout.flush()
                return True
            elif ch in ('n', 'N'):
                sys.stdout.write('n\n')
                sys.stdout.flush()
                return False
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def colorize_git_status(status: str) -> Text:
    text = Text()
    in_staged = False
    for line in status.splitlines():
        if line.startswith("On branch"):
            text.append(line + "\n", style="bold")
            in_staged = False
        elif line.startswith("Changes to be committed"):
            text.append(line + "\n", style="bold")
            in_staged = True
        elif line.startswith("Changes not staged") or line.startswith("Untracked files"):
            text.append(line + "\n", style="bold")
            in_staged = False
        elif in_staged and line.startswith("\t"):
            text.append(line + "\n", style="green")
        elif not in_staged and line.startswith("\t"):
            text.append(line + "\n", style="red")
        else:
            text.append(line + "\n", style="dim")
    return text


def format_commit_message(message: str) -> Panel:
    parts = message.split(":", 1)
    if len(parts) == 2:
        commit_type = parts[0].strip()
        color = COMMIT_TYPE_COLORS.get(commit_type, "bright_white")
        styled = Text()
        styled.append(commit_type, style=f"bold {color}")
        styled.append(":", style="bold white")
        styled.append(parts[1], style="bright_white")
    else:
        styled = Text(message, style="bright_white")

    return Panel(styled, title="[bold]Suggested Commit[/bold]", border_style="bright_blue", padding=(0, 2))


def cmd_run(env: dict, skip_suffix: bool = False):
    status = subprocess.run(
        ["git", "status"],
        capture_output=True, text=True,
        env={**os.environ, "LC_ALL": "C", "LANG": "C"},
    ).stdout
    console.print(Panel(colorize_git_status(status.rstrip()), title="[bold]Git Status[/bold]", border_style="blue"))

    if has_commits() and not has_staged_files():
        console.print("\n[bold red]No staged files.[/bold red] Please run [yellow]`git add`[/yellow] before committing.\n")
        sys.exit(1)

    if not has_commits():
        message = _generate_with_cancel(env, initial=True)
    else:
        diff = get_git_diff()
        if not diff:
            console.print("[bold red]No changes detected.[/bold red]")
            sys.exit(1)
        message = _generate_with_cancel(env, diff=diff)

    if message is None:
        console.print("[yellow]Aborted.[/yellow]")
        sys.exit(0)

    if not skip_suffix:
        suffix = _read_line_or_esc("\n[dim]Issue ID or note for the () suffix[/dim] [dim](ESC to abort)[/dim]: ")
        if suffix is None:
            console.print("[yellow]Aborted.[/yellow]")
            sys.exit(0)
        suffix = suffix.strip()
        if suffix:
            message = f"{message} ({suffix})"

    console.print()
    console.print(format_commit_message(message))

    confirmed = _confirm_or_esc("\n[bold]Commit?[/bold] [dim](y/n/ESC)[/dim] ")
    if not confirmed:
        console.print("[yellow]Aborted.[/yellow]")
        sys.exit(0)

    result = subprocess.run(["git", "commit", "-m", message])
    if result.returncode == 0:
        console.print("\n[bold bright_green]Committed successfully![/bold bright_green]")
    sys.exit(result.returncode)


def cmd_test(env: dict):
    console.print(f"[dim]Testing config:[/dim] url=[cyan]{env['url']}[/cyan] model=[cyan]{env['model']}[/cyan]")
    client = OpenAI(base_url=env["url"], api_key=env["key"])
    with console.status("[cyan]Pinging model...[/cyan]"):
        response = client.chat.completions.create(
            model=env["model"],
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=16,
        )
    console.print(f"[green]Response:[/green] {response.choices[0].message.content.strip()}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autocommit")
    parser.add_argument("-e", "--env", dest="env_name", default=None, help="Config env name (default: first in config)")

    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Generate a commit message and commit (default)")
    run_parser.add_argument("-n", "--no-suffix", action="store_true", help="Skip the issue ID suffix prompt")

    subparsers.add_parser("test", help="Ping the configured model to verify connectivity")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    config = load_config()
    env = get_env(config, args.env_name)

    if args.command == "test":
        cmd_test(env)
    else:
        config_no_suffix = env.get("arguments", {}).get("no_suffix", False)
        cli_no_suffix = getattr(args, "no_suffix", False)
        cmd_run(env, skip_suffix=config_no_suffix or cli_no_suffix)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(130)
