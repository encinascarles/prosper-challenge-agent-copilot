#
# Prosper AI's API — building an agent from a clinic's guidelines, and talking
# to Prosper AI in the pull request it works on.
#
# Creating an agent this way takes a form (multipart): its name, the pasted
# notes and the files. The files are read here, before anything is stored, so
# one that cannot be read (a scan, a format we do not take) is a 422 with the
# reason while the dialog is still open. Then the agent is created with its
# PR #1, opened by Prosper AI on an empty copy, and the build runs in the
# background (copilot/setup.py); the pull request's events say how it goes.
#
# Answering a question by picking an option needs no model: the option came
# with the rule it becomes. Anything written in the conversation goes to
# Prosper AI, as the answer to its open question or as a change to make.
#

from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints

import store
from copilot import files as reading
from copilot import setup
from store.db import now

from . import checks
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
    agent, pull = store.prosper.create_setup(name, sources, request, reading.summary(sources))
    setup.build(agent["id"], pull["number"])
    return {"agent": agent, "pull": pull}


@router.post(
    "/{agent_id}/pulls/{number}/answers", response_model=Pull, responses=_MISSING | _REFUSED
)
def answer(agent_id: str, number: int, body: Answer) -> dict:
    """Pick an option of Prosper AI's question: its rule goes into the copy."""
    get_pull(agent_id, number)
    pull, done = _answer(store.prosper.pick, agent_id, number, body.question, body.option)
    if done:
        checks.start(agent_id, pull=number)
    return store.get_pull(agent_id, number)


@router.post(
    "/{agent_id}/pulls/{number}/messages", response_model=Pull, responses=_MISSING | _REFUSED
)
def message(agent_id: str, number: int, body: Message) -> dict:
    """Write to Prosper AI: the answer to its open question, or a change to make."""
    if get_pull(agent_id, number)["prosper"] is None:
        raise HTTPException(
            status_code=409,
            detail="Prosper AI only works on the pull request it set up, for now.",
        )
    pull, answers, retry = _answer(store.prosper.take_message, agent_id, number, body.text)
    if retry is not None:
        setup.retry(agent_id, number, retry, body.text)
    else:
        setup.change(agent_id, number, body.text, answers)
    return pull
