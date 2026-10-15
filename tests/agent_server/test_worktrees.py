from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openhands.agent_server.conversation_service import (
    ConversationService,
    WorktreeNotRemovable,
    _ConversationRecord,
    _create_conversation_worktree,
    _plan_conversation_worktree,
)
from openhands.agent_server.dependencies import get_conversation_service
from openhands.agent_server.models import StoredConversation
from openhands.agent_server.worktrees_router import worktrees_router
from openhands.sdk.conversation.state import ConversationExecutionStatus
from openhands.sdk.git.utils import run_git_command
from openhands.sdk.security.confirmation_policy import NeverConfirm
from openhands.sdk.workspace import LocalWorkspace


@pytest.fixture
def service(tmp_path) -> ConversationService:
    service = ConversationService(
        conversations_dir=tmp_path / "conversations",
        conversation_worktree_root=tmp_path / "worktrees",
    )
    service._event_services = {}
    return service


@pytest.fixture
def repo(tmp_path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# repo\n")
    run_git_command(["git", "init", "-b", "main"], repo)
    run_git_command(["git", "add", "README.md"], repo)
    run_git_command(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "init"],
        repo,
    )
    return repo


def worktree_conversation(
    service: ConversationService, repo: Path
) -> StoredConversation:
    conversation_id = uuid4()
    plan = _plan_conversation_worktree(
        LocalWorkspace(working_dir=repo),
        conversation_id,
        service.conversation_worktree_root,
    )
    assert plan is not None
    stored = StoredConversation(
        id=conversation_id,
        workspace=_create_conversation_worktree(plan),
        confirmation_policy=NeverConfirm(),
    )
    (service.conversations_dir / conversation_id.hex).mkdir(parents=True)
    service._conversation_records[conversation_id] = _ConversationRecord(
        stored=stored, execution_status=ConversationExecutionStatus.IDLE
    )
    return stored


def branches(repo: Path) -> str:
    return run_git_command(["git", "branch", "--list"], repo)


@pytest.mark.asyncio
async def test_a_clean_worktree_is_removed_and_comes_back_on_reopen(service, repo):
    stored = worktree_conversation(service, repo)
    checkout = Path(stored.workspace.working_dir)

    [worktree] = await service.list_worktrees()
    assert worktree.conversation_ids == [stored.id]
    assert worktree.branch == f"openhands/{stored.id}"
    assert worktree.size_bytes > 0
    assert not worktree.has_changes and not worktree.in_use

    # Untracked work keeps it.
    (checkout / "notes.txt").write_text("draft")
    [worktree] = await service.list_worktrees()
    assert worktree.has_changes
    with pytest.raises(WorktreeNotRemovable):
        await service.remove_worktree(worktree.name)

    (checkout / "notes.txt").unlink()
    await service.remove_worktree(worktree.name)

    assert await service.list_worktrees() == []
    assert f"openhands/{stored.id}" in branches(repo)
    meta = (service.conversations_dir / stored.id.hex / "meta.json").read_text()
    assert StoredConversation.model_validate_json(meta).removed_worktree is not None

    # Reopening the conversation checks its branch out again.
    service._prepare_persisted_runtime(service._conversation_records[stored.id].stored)
    assert (checkout / "README.md").is_file()
    assert run_git_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], checkout) == (
        f"openhands/{stored.id}"
    )


@pytest.mark.asyncio
async def test_an_open_conversation_keeps_its_worktree(service, repo):
    stored = worktree_conversation(service, repo)
    assert service._event_services is not None
    service._event_services[stored.id] = MagicMock(is_open=lambda: True)

    [worktree] = await service.list_worktrees()

    assert worktree.in_use
    with pytest.raises(WorktreeNotRemovable):
        await service.remove_worktree(worktree.name)


@pytest.mark.parametrize(
    ("name", "status", "body"),
    [
        # A JSON body, not an empty 204: clients parse the response.
        ("clean", 200, {"removed": True}),
        # Never anything outside the worktree root.
        ("..", 404, None),
        ("missing", 404, None),
        ("in-use", 409, None),
    ],
)
def test_remove_route_statuses(service, repo, name, status, body):
    stored = worktree_conversation(service, repo)
    if name in ("clean", "in-use"):
        if name == "in-use":
            assert service._event_services is not None
            service._event_services[stored.id] = MagicMock(is_open=lambda: True)
        name = Path(stored.workspace.working_dir).parent.name
    app = FastAPI()
    app.include_router(worktrees_router)
    app.dependency_overrides[get_conversation_service] = lambda: service

    response = TestClient(app).delete(f"/worktrees/{name}")

    assert response.status_code == status
    if body is not None:
        assert response.json() == body
    assert service.conversation_worktree_root.parent.is_dir()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["..", ".", "../repo"])
async def test_nothing_outside_the_worktree_root_is_removed(service, repo, name):
    worktree_conversation(service, repo)

    with pytest.raises(KeyError):
        await service.remove_worktree(name)

    assert (repo / "README.md").is_file()
    assert len(await service.list_worktrees()) == 1
