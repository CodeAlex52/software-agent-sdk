"""Conversation worktrees under the server's worktree root, for cleanup."""

from fastapi import APIRouter, Depends, HTTPException, status

from openhands.agent_server.conversation_service import (
    ConversationService,
    WorktreeNotRemovable,
)
from openhands.agent_server.dependencies import get_conversation_service
from openhands.agent_server.models import ConversationWorktree


worktrees_router = APIRouter(prefix="/worktrees", tags=["Worktrees"])


@worktrees_router.get("")
async def list_worktrees(
    conversation_service: ConversationService = Depends(get_conversation_service),
) -> list[ConversationWorktree]:
    """List conversation worktrees with their size, activity and changes."""
    return await conversation_service.list_worktrees()


@worktrees_router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_worktree(
    name: str,
    conversation_service: ConversationService = Depends(get_conversation_service),
) -> None:
    """Remove a clean worktree no open conversation uses; its branch stays.

    Reopening one of its conversations re-creates it from that branch.
    """
    try:
        await conversation_service.remove_worktree(name)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Worktree not found") from None
    except WorktreeNotRemovable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
