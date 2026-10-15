"""Storage of host-local conversations: their git worktrees."""

import os
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from openhands.agent_server.utils import safe_rmtree
from openhands.sdk.logger import get_logger
from openhands.sdk.utils.command import sanitized_env


logger = get_logger(__name__)


def conversation_worktree_dir(root: Path, working_dir: str) -> Path | None:
    """The dir under ``root`` holding a workspace's worktree, if any.

    Not always ``root/<id>``: a fork shares its source's workspace.
    """
    try:
        rel = Path(working_dir).resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return root / rel.parts[0] if rel.parts else None


def remove_conversation_worktree(conversation_dir: Path) -> None:
    """Remove the worktrees in a conversation dir; their branches stay."""
    if conversation_dir.is_symlink() or not conversation_dir.is_dir():
        return
    repos = [
        repo for worktree in _worktrees(conversation_dir) if (repo := _repo(worktree))
    ]
    if not safe_rmtree(conversation_dir, f"conversation worktrees {conversation_dir}"):
        return
    # Drops git's record of the missing worktree; the branch is untouched.
    for repo in repos:
        _git(repo, "worktree", "prune")


@dataclass(frozen=True)
class WorktreeStatus:
    path: Path
    repository: Path | None
    branch: str | None
    # True too when git cannot tell: such a worktree is never removed.
    has_changes: bool


def describe_conversation_worktree(conversation_dir: Path) -> WorktreeStatus | None:
    """The worktree in a conversation dir, or None when it holds none."""
    worktrees = _worktrees(conversation_dir)
    if not worktrees:
        return None
    worktree = worktrees[0]
    common = _repo(worktree)
    status = _git(worktree, "status", "--porcelain")
    return WorktreeStatus(
        path=worktree,
        repository=common.parent if common and common.name == ".git" else common,
        branch=_git(worktree, "rev-parse", "--abbrev-ref", "HEAD"),
        has_changes=status is None or status != "",
    )


def directory_size(directory: Path) -> int:
    """Bytes of the files under ``directory``, not following symlinks."""
    total = 0
    for parent, _, files in os.walk(directory):
        for name in files:
            with suppress(OSError):
                total += (Path(parent) / name).lstat().st_size
    return total


def recreate_worktree(repository: str, path: str, branch: str) -> bool:
    """Check ``branch`` out again at ``path``, where its worktree was removed."""
    return _git(Path(repository), "worktree", "add", path, branch) is not None


def _worktrees(conversation_dir: Path) -> list[Path]:
    # A worktree's .git is a file pointing at the main repository.
    return [
        child
        for child in conversation_dir.iterdir()
        if not child.is_symlink() and (child / ".git").is_file()
    ]


def _repo(worktree: Path) -> Path | None:
    common = _git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(common) if common else None


def _git(cwd: Path, *args: str) -> str | None:
    result = subprocess.run(
        # The repo's config is agent-writable; fsmonitor would run it.
        [
            "git",
            "--no-optional-locks",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(cwd),
            *args,
        ],
        env=sanitized_env(),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        logger.warning("git %s failed in %s: %s", " ".join(args), cwd, result.stderr)
        return None
    return result.stdout.strip()
