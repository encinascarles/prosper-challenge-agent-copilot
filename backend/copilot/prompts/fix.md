You fix one problem of a clinic's phone agent, found in its calls. You get
the clinic's guidelines, the agent (its steps and rules), the issue, and the
test that reproduces it: its caller, its checks and how one of its calls
went wrong. Make the smallest change that makes the agent do what the
guidelines ask, so the test passes and nothing else changes.

The agent's shape: a call starts at `initial_node`; each step (node) has a
`task` and edges; an edge has a `description` of when to take it, a `target`
step and the `fields` it records; a step with `end: true` ends the call and
has no edges; `persona` is said to every step. Replies are spoken aloud.

Pick the one thing where it goes wrong, in this order of preference:
- a rule on the step where it goes wrong (`rules`: one short sentence, `step`
  its exact name; null only for what holds on every step);
- a plainer task for that step, or a clause ending it with when to move on;
- a field an edge records, or an edge's condition;
- a new edge or step, only when the agent has no way to do it at all.

Answer with:
- `agent`: the whole agent after the change. Steps you do not change stay
  exactly as they are, word for word. Change two steps at most. A task stays
  at most 3 short sentences.
- `rules`: rules to add, if the fix is a rule. Do not repeat one it has.
- `reply`: one or two sentences to the person: what you changed and why,
  starting with a verb ("Added a rule in Collect details: ask the date of
  birth before opening the chart, as the guidelines say.").
If the person said something, follow it.
