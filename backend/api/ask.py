#
# Ask Prosper AI's API — chats about an agent, outside any pull request.
#
# Asking is one request that waits for the answer: Prosper AI answers with one
# request to the model, in seconds, so there is nothing to follow in the
# background. The question is stored first, so it stays in the chat even if
# answering fails; the answer says so then.
#
# A chat only answers. When the person asks for a change, the answer offers a
# pull request, and taking the offer opens it (kind "change"), with Prosper AI
# working on it as on a fix: copilot/fix.py.
#

from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field, StringConstraints

import store
from copilot import ask, setup

from .models import Problem
from .pulls import _MISSING, _REFUSED, Pull, _answer

router = APIRouter(prefix="/api/agents/{agent_id}/chats", tags=["Ask Prosper AI"])

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class Question(BaseModel):
    text: Text = Field(examples=["Can Anna book for a child?"])
    pull: Optional[int] = Field(
        None, description="The open pull request the person is on; none for live."
    )


class Link(BaseModel):
    kind: Literal["issue", "pull", "call"]
    number: int  # the issue's or pull request's number, or the call's id


class Offer(BaseModel):
    """A change asked for in the chat, as a pull request it can open."""

    title: str  # one line: "Ask who the visit is for"
    what: str  # what it would change
    pull: int | None  # the pull request it opened, once taken


class ChatMessage(BaseModel):
    by: str  # "you" or "Prosper AI"
    at: str
    text: str
    about: str | None = None  # Prosper AI's: what it answered from, "v2" or "PR #5"
    links: list[Link] = []  # what the answer names that can be opened
    offer: Offer | None = None
    failed: bool = False  # Prosper AI could not answer


class ChatSummary(BaseModel):
    id: int
    title: str  # its first question
    pulls: list[int]  # the pull requests its offers opened
    count: int  # of messages
    created_at: str
    updated_at: str


class Chat(ChatSummary):
    messages: list[ChatMessage]
    usage: dict[str, float]  # what its answers cost: requests, tokens, USD


class Opened(BaseModel):
    pull: Pull
    chat: Chat


_NO_CHAT = {404: {"model": Problem, "description": "No such agent, chat or pull request."}}


@router.get("", response_model=list[ChatSummary], responses=_MISSING)
def list_chats(agent_id: str) -> list[dict]:
    """The agent's chats, the latest written in first."""
    return _answer(store.chats.list_chats, agent_id)


@router.post("", status_code=201, response_model=Chat, responses=_NO_CHAT)
def new_chat(agent_id: str, body: Question) -> dict:
    """Start a chat with a question, and get Prosper AI's answer."""
    chat = _answer(store.chats.create_chat, agent_id, body.text)
    return _answer(ask.answer, agent_id, chat["id"], body.pull)


@router.get("/{chat_id}", response_model=Chat, responses=_NO_CHAT)
def get_chat(agent_id: str, chat_id: int) -> dict:
    return _answer(store.chats.get_chat, agent_id, chat_id)


@router.post("/{chat_id}/messages", response_model=Chat, responses=_NO_CHAT)
def ask_more(agent_id: str, chat_id: int, body: Question) -> dict:
    """Ask Prosper AI something more in the chat, and get its answer."""
    _answer(store.chats.add_message, agent_id, chat_id, {"by": "you", "text": body.text})
    return _answer(ask.answer, agent_id, chat_id, body.pull)


@router.post(
    "/{chat_id}/messages/{index}/pull",
    status_code=201,
    response_model=Opened,
    responses=_NO_CHAT | _REFUSED,
)
def create_pull(agent_id: str, chat_id: int, index: int) -> Any:
    """Open the pull request message `index` offers; Prosper AI starts on it at once."""
    work = {"state": "working", "doing": "Writing a test of it", "questions": []}
    pull, chat = _answer(store.chats.open_offer, agent_id, chat_id, index, work)
    setup.fix(agent_id, pull["number"])
    return {"pull": pull, "chat": chat}
