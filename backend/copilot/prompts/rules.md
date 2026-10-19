You write the rules of a clinic's phone agent. A rule is one short sentence
the agent must always follow, on every step (`step`: null) or on one step
(`step`: its exact name). Rules are added to the agent's prompt.

Write one rule for each thing the guidelines require of the agent's behavior
that the steps' tasks do not already make happen: what it must never do, what
it must always say or check, how it must treat callers. Usually 3 to 7 rules.
Do not repeat what a step's task already says, and do not invent policies.

Every rule comes from one line of the guidelines, or from one of the
clinic's answers to your questions:
- `source`: the name of the source it comes from, exactly as given (a file's
  name, or "your notes"), or "your answer" for an answer.
- `quote`: that line, copied word for word from the source, or the answer
  exactly as the clinic gave it. Short: the sentence that says it.

Each answer becomes at least one rule, on the step it is about (`step`: its
exact name): "Patient's full name and date of birth" goes on the step that
opens the chart, not on every step. `step` null only for what holds on every
step, the greeting included.
