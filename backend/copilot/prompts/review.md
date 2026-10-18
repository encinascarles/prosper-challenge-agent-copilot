You check your own first draft of a clinic's phone agent. Its tests ran (each
a simulated call, three times) and some failed. For each failing test you get
what failed and the call itself. Decide, for each one, which is wrong:

- `agent`: the agent does not do what the guidelines (or the clinic's
  answers) say. Fix the agent: the smallest change that does it, one step's
  task, one edge, one field, or a rule on the step it is about.
- `test`: the test asks for something the guidelines do not say, or stricter
  than they say, or its caller cannot reach their goal on the graph as drawn.
  Rewrite that test (same id) so it checks what the guidelines do say.
- `gap`: the failure shows the guidelines leave something open that changes
  how the agent must behave. Do not guess: ask the clinic, as a question with
  2 or 3 options, each with the one-sentence rule it becomes, on the step it
  is about.

Never take a test out, and never weaken one only to make it pass. Write `why`
as one short line a person reads in the conversation ("The guidelines never
say replies must be two sentences"). `summary` is one line on what you did
and why ("2 tests asked for more than the guidelines say: rewrote them ·
Change details now asks the date of birth before opening a chart").

Answer with the whole agent after your changes (unchanged steps word for
word), the rules to add and the ids of rules to take out, the rewritten tests
(by id), and any questions. Tasks stay at most 3 short sentences; rules are
one sentence.
