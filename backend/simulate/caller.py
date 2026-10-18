#
# The simulated caller: a model playing the person a test describes, talking to
# the agent one line at a time, and hanging up when it is done or getting
# nowhere.
#
# It is our model, not the agent's (simulate/models.py): the agent runs on its
# own model, because that is what calls run; who plays the caller is up to us.
#

from typing import Optional

from openai import AsyncOpenAI

HANG_UP = "[HANGS UP]"

# The caller lets the agent end the call: a caller who hangs up after their own
# goodbye would fail "Ends the call" for the caller's manners, not the agent's.
_INSTRUCTIONS = (
    "You are on a phone call with an automated assistant, playing this person:\n\n{who}\n\n"
    "Reply with only what you say next: one or two short spoken sentences, nothing else. "
    "Do not hang up yourself: when you are done, say so and let the assistant end the call. "
    f"Reply exactly {HANG_UP} only if the description says you hang up, or if the assistant "
    "has said goodbye twice and the call still has not ended."
)


class Caller:
    """A model playing `who`, the caller a test describes."""

    def __init__(self, who: str, client: AsyncOpenAI, model: str):
        self.who = who
        self.client = client
        self.model = model
        self.tokens = {"prompt": 0, "completion": 0}

    async def reply(self, transcript: list[dict]) -> Optional[str]:
        """The caller's next line, given the call so far; None when they hang up."""
        messages = [{"role": "system", "content": _INSTRUCTIONS.format(who=self.who)}]
        # The agent is the other party: its lines are the "user" talking to the caller.
        for line in transcript:
            role = "user" if line["role"] == "agent" else "assistant"
            messages.append({"role": role, "content": line["text"]})
        response = await self.client.chat.completions.create(
            model=self.model, messages=messages, max_completion_tokens=600
        )
        self.tokens["prompt"] += response.usage.prompt_tokens
        self.tokens["completion"] += response.usage.completion_tokens
        line = (response.choices[0].message.content or "").strip()
        if not line or HANG_UP in line:
            return None
        return line
