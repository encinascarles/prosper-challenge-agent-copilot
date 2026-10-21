#
# Prosper AI's API — building an agent from a clinic's guidelines, and talking
# to Prosper AI in the pull request it works on.
#
# Creating an agent this way takes a form (multipart): its name, the pasted
# notes and the files. The files are read here, before anything is stored, so
# one that cannot be read (a scan, a format we do not take) is a 422 with the
# reason while the dialog is still open. Then the agent is created with its
# PR #1, opened by Prosper AI on an empty copy, and Prosper AI starts on it in
# the background with the setup brief (copilot/agent.py); the pull request's
# events say how it goes.
#
# Answering a question by picking an option needs no model: the option came
# with the rule it becomes. Once every question has its answer, Prosper AI
# goes on: the answers start its next turn. Anything written in the
# conversation of an open pull request is that next turn too, as the answer to
# its open question or as what to do next; fixing an issue starts from the
# issue (live.py). A fix that could not reproduce its issue asks whether to go
# on: the answer is acted on here, without the model, so going on is always
# the person's call.
#

from typing import Annotated, Any

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints

import store
from copilot import agent, work
from copilot import files as reading
from store.db import now

from .agents import NewAgent
from .models import YOU, Problem
from .pulls import _MISSING, _REFUSED, Pull, _answer, get_pull

router = APIRouter(prefix="/api/agents", tags=["Prosper AI"])

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

_UNREADABLE = {422: {"model": Problem, "description": "No guidelines, or a file it cannot read."}}


class Answer(BaseModel):
    question: str = Field(description="The question's id, from its event.")
    option: int = Field(ge=0, description="Which option, from 0.")


class Message(BaseModel):
    text: Text = Field(examples=["Make the greeting shorter."])


@router.post("/from-guidelines", status_code=201, response_model=NewAgent, responses=_UNREADABLE)
def from_guidelines(
    name: Annotated[str, Form()],
    guidelines: Annotated[str, Form()] = "",
    files: Annotated[list[UploadFile], File()] = [],  # noqa: B006 - FastAPI's way
) -> Any:
    """Create an agent that Prosper AI builds from `guidelines` and the files, in its PR #1."""
    name = name.strip()
    if not name:
        return JSONResponse(status_code=422, content={"detail": "The agent needs a name."})
    sources = []
    if notes := reading.notes(guidelines):
        sources.append(notes)
    try:
        for upload in files:
            sources.append(reading.read(upload.filename or "file", upload.file.read()))
    except reading.Unreadable as error:
        return JSONResponse(status_code=422, content={"detail": str(error)})
    if not sources:
        detail = "Paste the guidelines or attach a file: Prosper AI builds the agent from them."
        return JSONResponse(status_code=422, content={"detail": detail})
    read = [s for s in sources if s["name"] != reading.NOTES]
    request = {
        "type": "request",
        "by": YOU,
        "at": now(),
        "text": f"Build {name} from these guidelines.",
        "notes": notes["text"] if notes else None,
        "files": [{key: s[key] for key in ("name", "kind", "pages")} for s in read],
    }
    created, pull = store.prosper.create_setup(name, sources, request, reading.summary(sources))
    agent.start(created["id"], pull["number"])
    return {"agent": created, "pull": pull}


@router.post(
    "/{agent_id}/pulls/{number}/answers", response_model=Pull, responses=_MISSING | _REFUSED
)
def answer(agent_id: str, number: int, body: Answer) -> dict:
    """Pick an option of Prosper AI's question: its rule goes into the copy."""
    get_pull(agent_id, number)
    question = next(
        (
            q
            for q in store.prosper.work_of(agent_id, number).get("questions", [])
            if q["id"] == body.question
        ),
        None,
    )
    _, done, kind = _answer(store.prosper.pick, agent_id, number, body.question, body.option)
    if kind == "go_on":
        _go_on(agent_id, number, body.option == 0)
    elif done:
        said = "The clinic answered your questions." if kind == "setup" else None
        agent.start(agent_id, number, said or _answers_of(question, body.option))
    return store.get_pull(agent_id, number)


def _answers_of(question: dict | None, option: int) -> str:
    if question is None:
        return "They answered your questions."
    return f'They picked "{question["options"][option]["label"]}" for "{question["text"]}".'


def _go_on(agent_id: str, number: int, go: bool, said: str | None = None) -> None:
    """Go on with a fix that could not reproduce its issue, with the test it wrote, or stop."""
    if not go:
        work.leave_it(agent_id, number)
    elif work.keep_anyway(agent_id, number):
        words = f' Their words: "{said}"' if said else ""
        agent.start(agent_id, number, f"They said to go on without a reproduction.{words}")


@router.post(
    "/{agent_id}/pulls/{number}/messages", response_model=Pull, responses=_MISSING | _REFUSED
)
def message(agent_id: str, number: int, body: Message) -> dict:
    """Write to Prosper AI: the answer to its open question, or a change to make.

    On any open pull request: one Prosper AI has no part in yet starts its
    work with the message.
    """
    get_pull(agent_id, number)
    pull, answers, going = _answer(store.prosper.take_message, agent_id, number, body.text)
    if answers is not None and answers.get("kind") == "go_on":
        # Their own words are a go-ahead, with what they said for the fix.
        _go_on(agent_id, number, True, body.text)
    elif going:
        agent.start(agent_id, number, body.text)
    return store.get_pull(agent_id, number) if answers else pull
