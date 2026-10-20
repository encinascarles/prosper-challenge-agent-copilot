#
# Ask Prosper AI's API — chats about an agent, outside any pull request.
#
# Asking is one request that waits for the answer: Prosper AI answers in a few
# steps with the model, in seconds, so there is nothing to follow in the
# background. What it is asked about (live, or a pull request) is found
# first: a question about nothing is a 404 that stores nothing. Then the
# question is stored, so it stays in the chat even if the model fails; the
# answer says so then.
#
# Prosper AI reads with tools (tools.py) as it answers, and proposes acts as
# cards: the act runs only when the person takes the card (`decide`), which
# answers once it is done and Prosper AI has said what is next. Older chats
# may hold an offer of a pull request: taking it still opens it.
#

from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field, StringConstraints

import store
from copilot import ask, setup

from .models import Problem
from .pulls import _MISSING, _REFUSED, Pull, _answer
from .tools import TOOLS

router = APIRouter(prefix="/api/agents/{agent_id}/chats", tags=["Ask Prosper AI"])

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class Question(BaseModel):
    text: Text = Field(examples=["Can Anna book for a child?"])
    pull: Optional[int] = Field(
        None, description="The open pull request the person is on; none for live."
    )


class Link(BaseModel):
    # tests: the tests of PR `number`, or of live (0); calls, issues: their lists.
    kind: Literal["issue", "pull", "call", "tests", "calls", "issues"]
    number: int  # the issue's or pull request's number, or the call's id


class ActionResult(BaseModel):
    text: str  # "Opened Issue #14"
    link: Link | None


class Action(BaseModel):
    """Something Prosper AI proposes to do, done only when the person says so."""

    tool: str
    title: str  # "Merge PR #5 as v3"
    what: str  # its subject: the issue's or pull request's title, the rule
    meta: list[str]  # what follows from it: "Calls will use v3 from then on"
    stored: list[str] = []  # the words it will keep, a line each: a test's caller and checks
    # What the person should know before Do it, a line each: a fix whose test
    # passes 2 of 3. Do it is then their confirmation.
    warnings: list[str] = []
    # running: being done; skipped: the person wrote again instead
    state: Literal["pending", "running", "done", "failed", "declined", "skipped"]
    result: ActionResult | None = None  # once done
    error: str | None = None  # why it was refused, once failed


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
    reads: list[str] = []  # what it read to answer, a line each: "Read Issue #5"
    action: Action | None = None
    offer: Offer | None = None  # older chats: a pull request it offered
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


class Decision(BaseModel):
    do: bool = Field(description="Do it, or cancel it.")


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
    about = _answer(ask.copy_of, agent_id, body.pull)
    chat = _answer(store.chats.create_chat, agent_id, body.text)
    return _answer(ask.answer, agent_id, chat["id"], about, TOOLS)


@router.get("/{chat_id}", response_model=Chat, responses=_NO_CHAT)
def get_chat(agent_id: str, chat_id: int) -> dict:
    return _answer(store.chats.get_chat, agent_id, chat_id)


@router.post("/{chat_id}/messages", response_model=Chat, responses=_NO_CHAT)
def ask_more(agent_id: str, chat_id: int, body: Question) -> dict:
    """Ask Prosper AI something more in the chat, and get its answer."""
    about = _answer(ask.copy_of, agent_id, body.pull)
    _answer(store.chats.add_message, agent_id, chat_id, {"by": "you", "text": body.text})
    return _answer(ask.answer, agent_id, chat_id, about, TOOLS)


@router.post(
    "/{chat_id}/messages/{index}/action", response_model=Chat, responses=_NO_CHAT | _REFUSED
)
def decide(agent_id: str, chat_id: int, index: int, body: Decision) -> dict:
    """Do or cancel what message `index` proposes. Done, Prosper AI says what is next."""
    return _answer(ask.decide, agent_id, chat_id, index, body.do, TOOLS)


@router.post(
    "/{chat_id}/messages/{index}/pull",
    status_code=201,
    response_model=Opened,
    responses=_NO_CHAT | _REFUSED,
)
def create_pull(agent_id: str, chat_id: int, index: int) -> Any:
    """Open the pull request message `index` of an older chat offers; Prosper AI starts on it."""
    work = {"state": "working", "doing": "Writing a test of it", "questions": []}
    pull, chat = _answer(store.chats.open_offer, agent_id, chat_id, index, work)
    setup.fix(agent_id, pull["number"])
    return {"pull": pull, "chat": chat}
