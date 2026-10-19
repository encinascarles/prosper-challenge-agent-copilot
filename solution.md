# Solution

> Work in progress. This document grows with each PR: every key decision is
> recorded here in the same PR that implements it.

## The problem, as I read it

Prosper's deployment team spends its time on two manual loops:

1. **Initial implementation.** A clinic hands over natural-language guidelines
   (how to greet, what to collect, when to escalate, which visits need what) and
   someone translates them into a working agent graph.
2. **Production iteration.** Clients flag issues, or issues hide in call data.
   Someone has to find them, work out which part of the agent caused them, change
   it, and make sure the fix does not break something else. Finding the issues is
   itself a large part of the cost.

The builder UI (Phase 1) is the surface; the Copilot (Phase 2) is the point. The
measure of success is how much of those two loops it takes off the team's hands.

## Scope

_What is built, what is mocked, and what is deliberately left out, with the
reason for each. Filled in as the build progresses._

## Architecture

_Overview diagram and the main components. Filled in as the build progresses._

## Key decisions

### Frontend: Vite + React + TypeScript SPA

**Context.** The backend already exists in Python: Pipecat's FastAPI server runs
the voice pipeline, and the Copilot has to live next to `AgentBuilder` to work on
the real agent format. The UI needs a graph editor and an in-page WebRTC call.

**Options.**
- *Full-stack JS framework (Next.js, Remix).* Rejected: it brings a second server
  runtime, and logic would split between TypeScript and Python for no gain.
- *Python UI (Streamlit, Gradio).* Rejected: no native graph editor (React Flow
  would have to be wrapped anyway), a rerun-per-interaction model that fights a
  stateful canvas plus a live call, and weak WebRTC integration.
- *Client-only React SPA built with Vite.* Chosen.

**Trade-offs.** Minimal tooling and one backend. The dev server proxies `/api` to
FastAPI, so the browser sees one origin. Direct access to React Flow and Pipecat's
React client. Cost: two dev servers locally, hidden behind `make dev`.

**Styling: Tailwind + shadcn/ui.** The brief values judgement over polish, so the
UI should look decent at near-zero design cost. shadcn copies accessible
components into the repo (owned code, no runtime component library).

### Storage: SQLite, with the agent JSON in one column

**Context.** Agents have to survive a restart and be listed, opened and saved by
the editor. Phase 2 adds calls, issues and tests that point at agents.

**Options.**
- *JSON files, one per agent.* Rejected: enough for today, but calls and issues
  need queries across records ("the calls of this agent with an open issue"), and
  that would mean moving everything later.
- *A hosted database (Postgres).* Rejected: a server to install and configure
  before the reviewer can run anything, for a single-process app.
- *SQLite through the stdlib `sqlite3` module.* Chosen.

**Trade-offs.** Zero setup and no new dependency: the file is created and seeded
with the example agent on first start. No ORM and no migrations tool, which is
fine for one table and will need revisiting if the schema grows. The agent is
stored whole in one TEXT column, as `AgentConfig` reads it: nothing queries inside
the graph, so tables for nodes and edges would only be a mapping to keep in sync.
Deleting an agent removes it for good, versions and pull requests included,
so the editor asks first. Only a database that is being created is
seeded. One whose last agent was deleted stays empty, or the example would come
back on its own at the next start.

### Node positions live next to the agent, not in it

**Context.** The editor has to reopen a graph the way it was left, so where each
node sits must be saved. The agent JSON is what Pipecat runs and what the Copilot
reads and rewrites.

**Options.**
- *A `position` on each node of the agent JSON.* Rejected: a canvas coordinate is
  not part of an agent. It would reach the schema, the builder and every prompt
  that carries the agent, and moving a node would count as changing the agent.
- *The browser's local storage.* Rejected: the arrangement would be lost on
  another device, and it is part of how the team reads a flow.
- *A `layout` column next to `config`: `{ "<node name>": { "x", "y" } }`.* Chosen.

**Trade-offs.** Creating an agent and saving a pull request's copy take the same
body, `{ config, layout? }`, and both are written in one statement, so they
cannot be saved apart; a version keeps the layout it was merged with. The store drops positions of
names that are not nodes of the agent on every save, with or without a layout in
the request, so the layout never refers to a node that is gone. A client that
leaves the layout out (the Copilot applying a fix) keeps the stored one; a node
without a position is fine, the editor places it. Cost: the layout is keyed by
node name, so a rename has to carry the position over, which is the editor's job
since it knows the old name. Existing databases get the column added at startup
(a check on `PRAGMA table_info`), the one migration so far and still short of
needing a tool.

### The API lives on Pipecat's FastAPI app

**Context.** The Pipecat runner already starts a FastAPI server for the call
signalling, and exposes its `app` for extra routes.

**Options.**
- *A second service for the builder API.* Rejected: two processes and two ports
  to run, and CORS between them.
- *Mount an `APIRouter` on the runner's app.* Chosen.

**Trade-offs.** One backend, one port and one origin for the browser: calls and
agents go through the same `/api`. `bot.py` only does the wiring; the routes are
in `api/` and persistence in `store/`. The bot runs in the same process, so it
reads the agent a call was started for (and will save its calls) straight through `store`,
with no HTTP between services. Cost: the API starts with the runner, so
it is tied to how Pipecat builds its app. The tests avoid that by mounting the
same router on a bare FastAPI app.

### Validation errors say where the problem is

**Context.** An agent is saved only if `AgentBuilder` accepts it, the same code
that compiles the graph for a call. Its message is what the API returns, so it
has to be usable: the editor points at the broken node with it, and the Copilot
will read it to repair its own output.

**Options.**
- *Catch `KeyError` / `TypeError` in the API.* Rejected: `KeyError: 'name'` cannot
  say whether the agent, a node or an edge is missing its name.
- *Move the schema to Pydantic.* Rejected: its errors locate by index
  (`nodes.1.edges.0.target`), and it means rewriting the dataclass schema that
  came with the challenge for a gain the builder's graph checks would not share.
- *Check each field in `schema.py` as `from_dict` reads it.* Chosen.

**Trade-offs.** Messages use names, not indexes ("Missing required field 'target'
in edge 'choose_intent' of node 'greeting'."), and everything that loads an agent
gets the same ones. The schema stays one set of dataclasses. Cost: a small
hand-written checker instead of a library, and the request body is an untyped
object in the OpenAPI docs (the example agent is shown instead). The tests pin
each sentence, because they are a contract.

### Versions and pull requests: nothing reaches callers except by merging

**Context.** Everything the Copilot will do (set up an agent from guidelines,
fix an issue found in calls, refine a fix after a comment) produces a proposed
change that someone reviews, tries and then puts in front of callers. A person
editing by hand does the same. Until now saving overwrote the agent, so every
save went straight to the next call.

**Options.**
- *Keep overwriting, and record each save as a version to roll back to.*
  Rejected: a change still reaches callers before anyone has tried it, and the
  Copilot's edits would too.
- *One draft per agent, then "publish".* Rejected: one draft cannot hold two
  proposals at once (Prosper fixing one issue while someone edits by hand), and
  a published version would not say why it exists.
- *Live versions, and pull requests that each hold their own copy.* Chosen.

**Trade-offs.** An agent has versions v1, v2…, immutable snapshots of its config
and layout; the latest is live and calls run on it. A pull request is based on
the version that was live when it was opened and holds a whole copy of the
agent, which is what the editor saves to. Merging checks that copy with the
same `AgentBuilder` validation (422 naming the node and edge), adds the next
version from it and records which PR it came from, so the history answers "why
is this live". Whole copies rather than patches: an agent is a few kilobytes,
and a diff is computed when there is a screen to show it on.

A new agent starts with PR #1, "Set up <name>", based on nothing: it is not live
until that is merged, so even the first version goes through the same door.
Before that, the agent is what PR #1 holds, name included. The name is part of
the agent JSON, so renaming a live agent is a change like any other. A database
from before versions is migrated at startup: each agent becomes v1 from its
stored graph, with no PR, and its row keeps only what is not versioned (id,
name, the PR counter). Still no migrations tool: `CREATE TABLE IF NOT EXISTS`
and a one-off backfill, in one transaction.

A merge is refused (409) once live has moved past what the PR was based on: its
copy is of an older agent, and merging it would quietly undo whatever went live
in between. The PR says "Needs update · based on v1" until it is updated (see
the next decision). Every store operation takes the
write lock up front (`BEGIN IMMEDIATE`), so two merges cannot both read "live is
v1" and both become v2.

In the editor, live is never saved to. The first edit on live that changes the
agent opens a PR, "Your edits", and the edit lands there with its undo intact;
a toast says so and the pill switches to it. Moving cards or Tidy up is not a
change to the agent, so on live it opens nothing and is not kept. A test call
runs what the editor is on: the start body carries the agent id and, on a PR,
its number. Production calls will only ever name the agent, so they run live.

PRs are numbered per agent from one counter that issues will share, so "PR #5"
and "Issue #3" never collide; the UI always writes the prefix. Each PR keeps a
small log (opened, saved, merged, closed, reopened, updated: by whom, when) as JSON in its row,
since it is only read with its PR. There are no accounts: the person using the
builder is "you" in that log, and Prosper will sign its own changes.

API: `GET /api/agents[/{id}]` add `live_version` (0 until PR #1 merges) and the
open PR count; `POST /api/agents` returns the agent and its PR #1;
`GET …/versions[/{n}]`; `GET …/pulls?state=`, `POST …/pulls` (`{title}`, a copy
of live), `GET`/`PUT`/`PATCH` (title) `…/pulls/{n}`, `POST …/pulls/{n}/merge`,
`…/close`, `…/reopen` and `…/update`. There is no route that writes over an
agent or a version.

### A pull request is read on its own page, and updated by replaying it

**Context.** A pull request could only be seen through the pill and the bar in
Build, which say which one you are on but not what it changes or what happened
to it. Reviewing a change, and soon reading what Prosper did, needs a place of
its own. And a PR left behind by a merge could only wait: there was no way to
bring it onto the new live version.

**What.** Pull requests are a section next to Build: a list (Open · Merged ·
Closed) and a page per PR with its actions, its Conversation (the log, newest at
the bottom, where Prosper's turns will go) and its Changes. The section and the
page are in the URL, so a link lands on the same place. A closed PR keeps its
conversation and can be reopened as it was; if live moved on meanwhile, it needs
an update like any other.

**Changes are computed where they are shown.** Copies are stored whole, so the
diff is a pure function in the browser (`frontend/src/pulls/diff.ts`) over the
PR's copy and the version it is based on, worded for a non-engineer: steps
added, removed and renamed, instructions word by word, ways out added, removed
or moved, fields and the agent's settings. Stored copies carry no node ids (the
JSON mirrors Flows' `NodeConfig`, and ids would be one more thing every writer
has to keep stable), so a step is followed by its name and, when the name is
gone, by what it says: a renamed step keeps its instructions and edges.

**Update replays the PR's changes on live.** Options:
- *Rebuild the PR by hand on live.* Rejected: it is the manual work the product
  is meant to remove.
- *A three-way merge on the server.* Rejected for now: the same step matching
  would live twice, in Python for the merge and in TypeScript for the Changes
  tab, and drift.
- *Replay in the browser, checked by the server.* Chosen. The browser replays
  with the same matching the diff uses and sends the result with the version it
  replayed on (`onto`). The server takes it only if that version is still live
  (409 otherwise, so a merge in between cannot slip under it) and if it is a
  valid agent (422 naming where, as on save).

What only one side changed is taken from it. Where both changed the same thing
(the same instructions, say), the PR wins: it is the change under review, and
live is still there to compare with. The event says so ("Updated to v2 · kept
your text in Confirm"). A step the PR edited and live removed is kept with the
edit; edges left pointing at a removed step are dropped, and the Changes tab
shows the result before anyone merges it.

**Summaries travel with the events.** Each save and update carries one line on
what it changed, written by whoever made the change: the editor diffs what it
saves against the last save (following steps by id, so even a rename and a
rewrite in one save is one step), and Prosper will write its own. The server
stores the line, it does not derive it.

**Trade-offs.** A merge through the API alone cannot update a stale PR without
a client that replays; when Prosper needs to, the replay moves to the server as
one implementation. A step renamed *and* mostly rewritten on one side between
two versions shows as removed and added.

### Rules sit next to the agent JSON, and the builder puts them in the prompt

**Context.** Most fixes to an agent are not a new step: they are one sentence
it must follow ("read the date back before saying goodbye", "never give
medical advice"), everywhere or in one step. Prosper AI will add them for
each issue it fixes, and each has to say where it came from.

**Options.**
- *Edit the step's instructions.* Rejected: the sentence melts into text the
  person wrote, nothing says where it came from, and taking it out again
  means finding it.
- *A `rules` field inside the agent JSON.* Rejected: the JSON mirrors Flows'
  `NodeConfig`, and the cards edit it; rules would be one more thing every
  writer of the graph has to carry along.
- *A list next to the config, like the layout, compiled in by `AgentBuilder`.*
  Chosen.

**Trade-offs.** A rule is `{ id, step | null, text, source }`, stored with each
copy (a version, a pull request) so it is versioned with the agent: a pull
request carries its own and the merge puts them live. `AgentBuilder(config,
rules)` appends the rules for every step to each node's role message and a
step's own as one more task message of that node. Every runner goes through
the builder, so a voice call, a test call and a test all get the same prompt.
A rule names its step, so it follows a rename (the save sends the steps it
renamed) and goes with a removed step, like a position in the layout. A pull
request can only add rules and take out the ones it added; that keeps
replaying it on a newer live version a simple union. Cost: what the model is
told is now in two places, the cards and the rail.

### Tests are text calls on the voice call's pipeline, run on every change

**Context.** The Copilot's loop needs proof: reproduce an issue with a test,
change the agent, and show the whole suite still passes before anything goes
live. That needs tests a person can write in a sentence, and a way to run
them that is cheap enough to do on every save.

**Options.**
- *A simulator of our own (a loop over the graph calling the LLM).* Rejected:
  it would test our reimplementation of Flows, not what calls run.
- *Voice calls with a synthetic caller.* Rejected: slow, paid per second of
  speech, and STT noise would make every result flaky.
- *The real pipeline without audio.* Chosen: the same `AgentBuilder`,
  `FlowManager` (through `start_flow`, now shared with `bot.py`) and LLM
  service, with caller lines going in as messages and a small processor where
  TTS would be, collecting what the agent says and the node messages it
  reports. The path comes from the same reporter as a voice call's.

**Trade-offs.** A test is `{ name, caller, checks }`: who calls (a model plays
them) and one check per line. "Reaches <step>", "Ends the call" and "<field>
is recorded" are decided from the path, exactly and for free; anything else
is judged by a model on the transcript, yes or no with one line why. A line
is a path check only when it names a step or a field the copy has; "Reaches a
decision about the doctor" is a sentence, so it is judged rather than failing
every run, and the form says which kind each line is before it runs. The
agent's turn ends at the end of a response that
called no function, a rule pinned by tests that run Pipecat's OpenAI service
on a scripted stream. Those tests found that the function-call frame, being a
system frame, can overtake the response's start, so calls are counted between
response ends.

**Models.** The agent runs on the model its own JSON names (gpt-4o for the
sample), because what is tested must be what calls run. The simulated caller
and the judge are ours, and they need judgment rather than latency: they play
a person from a paragraph and decide whether a transcript meets a sentence. So
they use the newest general model available on the key, `gpt-6.1-sol`, set by
one variable (`PROSPER_MODEL`) so it can change without touching code.

A simulated call does not always go the same way, so each test runs 3 times
and shows as 3/3, 2/3, 0/3. It passes at 3/3, is flaky at 2/3 and fails
below that. Only failing tests block a merge. A voice agent on an LLM does not
answer the same way every time: 2/3 shows that (in yellow, "flaky", in the
rail, the Checks tab and the bar) without letting one unlucky call in three
hold a merge back. Asking for 3/3 made most real suites red on calls that
went right two times out of three. Every change to a pull
request's copy (save, update, rule or test added or taken out) runs the whole
suite again, and a merge is refused until it passes (409 on the server, a
disabled button in the UI), PR #1 included. Each run stores a fingerprint of
the config, rules and tests it ran on, and a merge needs the latest run to
match the copy as it is now: a change stored a moment before its run starts
cannot slip through on the run before it. All calls of a suite run at once,
12 at a time.

**What it costs.** Measured on the sample agent: 5 tests × 3 calls took 26 s
of wall-clock (12.9 s per call on average) and about USD 0.25, almost all of
it the agent's own gpt-4o tokens, since each turn resends the whole context;
the caller and the judge add a few cents. To keep that from being paid for
nothing: a save that does not change the config, rules or tests (moving
cards) keeps the run it has; a new change cancels the run in progress, so a
burst of saves pays for the calls already started, not for a suite each; and
"Run again" is the only way to repeat a run on the same copy. At scale, the
next steps would be to run only the tests a change can affect (those whose
path goes through an edited step, and the new ones) and to make the full
suite run on demand or before a merge rather than on every save. They run on an event loop in a thread of their
own, so voice calls on the server's loop never wait behind them. Results are
written as each call finishes and the editor polls them every 1.5 s while a
run is going; a stream would be more moving parts for a run that lasts under a
minute. Only the latest run of each copy is kept, which is all the screens
show, and a merged pull request's run becomes its version's.

Cost: text is not voice. No STT errors, interruptions or latency are tested;
the tests check the graph and the prompts. A judged check can be wrong, which
is why its reason is always shown. And every save spends money, so the suite
stays small and the caller and judge use one configurable model.

### Prosper AI sets up a new agent inside its PR #1

**Context.** The first manual loop: someone reads a clinic's guidelines and
draws the agent by hand. The product already has the door everything goes
through (a pull request, its suite, a merge), so the question was how an AI
fills that door in, in a way a person can follow, correct and trust.

**What.** "Build it with Prosper AI" in the new agent dialog takes a name,
pasted notes and files (PDF, Word, text). The files are read on the server
before anything is stored (`pypdf`, `python-docx`; no OCR, so a scan is
refused with the reason while the dialog is open). The agent is created with
PR #1 opened by Prosper AI on an empty copy, and a background job fills it in,
logging each step in the PR's conversation as it lands. First it reads the
guidelines and asks what they leave open (up to three questions, 2–3 options
each, or says there is no gap). Nothing is drawn until every answer is in.
Then it draws the agent with the answers ("Drew 7 steps", the graph shows up
in Build), writes the rules (each quoting its line, or the answer it comes
from, on the step it is about), and the tests last, from the guidelines and
the answers. Build and the PR page poll the
PR every second while it works; a stream would be more moving parts for a job
of about a minute. Meanwhile the copy is Prosper AI's: Build is read-only and
the API refuses the person's saves to it (409), so the two never write over
each other.

**One structured request per artifact, checked in code.** Options:
- *An agent framework (tool calls in a loop).* Rejected: the steps are known,
  and a loop that decides them is harder to read, test and price.
- *One request for everything.* Rejected: one bad part fails the whole answer,
  and nothing can be shown until all of it is written.
- *Questions, then the agent, its rules and its tests, each one request with
  a strict JSON schema.* Chosen. Plain OpenAI SDK (`copilot/llm.py`).

**Why questions first and tests last.** At first the questions came after the
agent and its tests were written. An answer turned into a rule then
contradicted both: the clinic asked for a date of birth before opening a
chart, the test callers had none to give, and the self-check spent its rounds
blaming the agent. Asked first, an answer shapes what gets drawn. Written
last, the tests check the agent the clinic described.

Each answer is checked in code and, when refused, sent back with the sentence
that says why (twice at most): the agent goes through `AgentBuilder` exactly as
a save, plus no dead ends and some end; a rule's quote must be in its source
word for word (a made-up quote would point at a sentence nobody wrote); a
test's "Reaches X" / "X is recorded" must name a real step or field. Strict
mode cannot describe an edge's `properties` (a JSON-schema object keyed by
field name), so the model writes the agent in a shape of its own (an edge
lists its fields) and code turns it into `AgentConfig`, with snake_case names
and `go_to_<target>` functions as the editor makes them. The voice agent keeps
gpt-4o; Prosper AI uses `PROSPER_MODEL`. Prompts are short files in
`copilot/prompts/`.

**Questions, answers and requests.** A setup question is answered by picking
an option or writing in the composer. Either way the answer is kept for the
drawing and becomes a rule quoting it (source "Your answer in PR #1"). A
question the self-check asks later comes with the rule each option becomes,
so picking one is a write with no model call. Anything written in the
composer goes to Prosper AI: the answer in your own words, or a change ("make
the greeting shorter"). It rewrites PR #1's copy through the same checks, adds
or takes out rules and tests (only those PR #1 added), sees what failed in the
last run and why, says what it changed, and the suite runs again.

**Checking its own draft.** A first draft fails some of its own tests, and
fixing that by hand (taking tests out, adding rules) is the manual work this
is meant to remove. So when a run that follows a change of Prosper AI's own
fails, it reads each failing test's runs and gives it one verdict, written
as a line in the conversation: the agent is wrong (it makes the smallest
change), the test asks for more than the guidelines say (it rewrites the
test in place and says why), or the guidelines leave a gap (it asks the
clinic). It never takes a test out, and code checks that every failing test
got a verdict and that each verdict did what it says. Two rounds at most,
then it says what still fails and hands over: past that, more rounds mostly
spend money on a flaky model. Everything it writes is held short in code (a
task at most three sentences, a rule one, a test 2–4 checks with at most one
judged and none about style), and every problem of an answer goes back at
once, since refusing on the first one let the model fix one thing and break
another.

**When it stops halfway.** Jobs run in the server's process, so a restart
marks any work still going as interrupted. Prosper AI remembers the job it is
on: a message after a failure retries it, the setup from the step it stopped
at, an answer still tied to its question. While it works, the person's
changes to that copy (an option clicked included) wait.

**What it costs, measured.** A setup from the sample PDF and DOCX: 5 requests,
about 8k tokens in and 3k out, USD 0.05; graph drawn 40 s after the click,
questions at 56 s; a change request 20–50 s and USD 0.02–0.04. The suite after
it dominates: 9 tests × 3 calls in 38 s, about USD 0.26, mostly the agent's own
gpt-4o. Two things found on the way: at default reasoning effort a request
could think for minutes and spend its whole token budget writing nothing, so
requests use low effort; even then, on Chat Completions, about one agent
request in two thought to its 6,000-token limit and wrote nothing. The same
request through the Responses API thinks a few hundred tokens, so Prosper AI
uses that; a cut-off answer is still asked for once more.

A review or a change writes the whole agent back, and it ran past 6,000
tokens, so those two get 12,000. Even so, one review went to 12,000 tokens of
degenerate output (no thinking) and only succeeded on its retry.

**This round, measured.** Two setups from scratch through the UI, on the
sample files, answering every question with its first option, no hand edits.

- *Setup A* ran before the builder change below. Questions at 10 s, graph at
  76 s. Its first suite had 2 tests passing, 2 flaky and 3 failing; the
  self-check was then cut off twice and failed. It cost USD 0.77.
- *Setup B* ran after it. Questions at 10 s, graph at 55 s. Its first suite
  had 1 failing test; one self-check round fixed the agent, the suite came
  back with 5 passing and 2 flaky, and it was merged as v1 318 s after the
  click. It cost USD 1.14 (USD 0.20 of Prosper AI, USD 0.94 for 2 suites).

Setup A's runs showed why calls failed. Mostly, the voice model did the next
step's work in the current one and said goodbye itself: no function was
called, so the call never moved and never ended. Asking Prosper AI for
plainer edges was not enough, so `AgentBuilder` now tells every step that
moves on to do only its own step and to call a function as soon as its
condition holds. That is the same for every agent and is compiled in, like
rules. The simulated caller also no longer hangs up after its own goodbye,
which used to fail "Ends the call" because of the caller rather than the
agent.

**Trade-offs and what is next.** The first agent is a draft: on the samples it
was sensible (greet, booking or change details, offer the two slots, confirm,
nurse callback, goodbye) but wordy, and its first suite failed where an answer
had become a rule for every step (the greeting began asking for a date of
birth). Earlier versions needed a person to get to green. One setup now got there
on its own, which is a single data point, not a rate.
Prosper AI only works in PR #1 for now; it cannot edit a rule in place (it
takes it out and adds another), it does not run tests itself to try a fix
before proposing it, and a test whose check is flaky has to be judged by a
person. Next: the same loop for issues found in calls, on PRs it opens.

### Calls come from simulated callers, and Prosper AI reviews every one

**Context.** The second manual job is reading production calls to find what
goes wrong. There is no call data here, and the live agent is whatever a setup
generated, so canned calls would not match it.

**Options.**
- *Seeded example calls and issues.* Rejected: they would describe some other
  agent, and nothing would change when the agent does.
- *Voice calls with a synthetic caller.* Rejected for the same reasons as for
  tests: slow, paid per second, and STT noise.
- *Simulated callers on the live version, through the tests' text pipeline.*
  Chosen. "Play calls" asks Prosper AI for a morning's mix of 10–12 callers
  from the clinic's guidelines and agent (mostly routine, 2+ edge cases: a
  symptom mid-booking, a time the clinic does not offer, a relative calling,
  everything said in one breath), then phones live with them, all at once and
  1.5 s apart. The UI says they are simulated wherever calls are listed.

**How a call is read.** As each call ends it is stored with the version that
answered, path, transcript and a length estimated from its words (there is no
audio to time), and Prosper AI reviews it in one structured request: the
checks it applied (3–8, taken from the rules first, then a guideline line or
a clinic answer), pass or fail, and one finding per failed check. A finding
names the agent's turn by its index and quotes it; the quote is checked word
for word, so the call and issue pages highlight a real line. Its step is read
from the transcript, not asked for. As for tests, a refused answer goes back
with the reason.

**Grouping.** A finding joins a tracked issue (open, snoozed or ignored) with
the same problem, or opens one. That is a second, small request, made only
when there is something to join, and grouping takes one call at a time while
reviews run in parallel, so two calls with the same new problem cannot both
open it. Issues take numbers from the counter pull requests use, so "Issue #3"
and "PR #4" never clash and the PR that fixes an issue can name it. An issue
is open, snoozed (a day, a week, or until the next version: checked when
issues are read, so nothing has to wake it), resolved (stops collecting;
if the problem comes back it is a new issue) or ignored (leaves the open list
but keeps counting calls).

**What the real runs showed.** A setup from the sample files, first option
everywhere, reached green on its first suite (6 passing, 1 flaky) and was
merged as v1 184 s after the click, USD 0.70 (0.11 Prosper AI, 0.59 the
suite). Three batches of 12 calls on that v1, about 80 s each:
- *Batch 1* filed 5 calls under "Presents unverified appointment times as
  available", a duty no guideline states. The audit prompt now says every
  check must come from a rule, a guideline line or an answer; batch 2 filed
  nothing more there.
- The real problems it found: symptoms mentioned mid-booking get "contact a
  healthcare provider" and more booking instead of the nurse callback the
  guidelines promise (Safety, 3 calls across batches); a relative's
  cancellation accepted without the chart check the clinic's answer requires;
  a cancellation claimed as done; date, time and place not read back.
- *Batch 3* opened a second issue for a problem already tracked, because it
  was said in another step. Grouping first only offered issues of the same
  step; it now offers every tracked issue, and a real grouping request put
  both findings where they belonged.

**What it costs.** A batch is USD 0.46–0.49: the calls 0.32–0.34 (almost all
the agent's own gpt-4o, which resends its context every turn; the prompt
cache barely helps), reviews 0.13 (about a cent each), the caller mix 0.02.
A call that goes nowhere is cut at 12 caller turns: one stuck call in the
first smoke run had cost USD 0.10 alone.

**Trade-offs and what is next.** Simulated callers are not customers: they
are cooperative and articulate, and they only hit what Prosper AI thought to
send them. The review is a model's reading and can be wrong, which is why
every finding shows the turn and why. Next: Fix with Prosper AI on an issue
(a test that reproduces it, then the change, in a pull request); voice test
calls stored as calls too; real call data in place of the simulated callers;
an issue that comes back after its fix reopening with a link to that fix.

### A test call runs the saved agent, and says where it is

**Context.** The editor holds a draft with unsaved changes, and a call has to run
some version of the agent. The bot runs in the backend; the draft only exists in
a browser tab.

**Options.**
- *Send the draft with the call.* Rejected: what was tested would be something
  that was never saved, and the next person to open the agent would not see what
  the call ran on. It also puts a whole agent in the body of a start request.
- *Start the call with the id of a saved agent.* Chosen.

**Trade-offs.** What you test is what goes live: the call reads the agent from
the store when it starts (the live version, or the saved copy of the pull
request the editor is on), so a passing test call is about the agent everyone
else sees. Cost: an edit has to be saved before it can be heard, so the editor
blocks the call while there are unsaved changes instead of quietly running the
older agent. A start that names no agent runs the sample flow, which keeps
Pipecat's prebuilt client at `/client` working as a way to check the voice
pipeline alone.

A wrong id fails at `POST /start`, with the same sentence the agents API gives.
The runner owns that route and, for WebRTC, only stores the body: the bot starts
later, on the browser's offer, when an error can no longer be an HTTP answer. So
the check sits in front of the route, as a middleware, and the bot runs it again
for an offer that skipped `/start`.

The call's path reaches the browser as messages on the RTVI channel the client
already has: `{ type: "node", node, from, edge, collected }`, once at the start
and on every node change. Flows has no transition event, but it runs a node's
pre-actions every time the node is entered, so each compiled node opens with a
`node_entered` action carrying those fields and the bot registers the handler
that sends it. That type is reserved: an agent that uses it in its own actions is
refused, with the reason, or its action would be reported as a node change. The builder states the fact and stays free of transports; a text simulation
can register another handler and record the same path. The alternative, reading
Pipecat's own function-call messages in the browser, would have left the UI to
work out the target from a function name and to guess the first node.

### The test call is read on the graph

**Context.** A test call answers "does the agent go where I meant it to?". The
transcript alone does not: the same sentence can come from two nodes, and what
the model passed to an edge is not said aloud.

**Options.**
- *Embed Pipecat's prebuilt client.* Rejected: it shows the conversation and
  nothing of the graph, and it cannot be told which agent to run.
- *A side panel with the call.* Rejected: it takes a third of the canvas from
  the thing the call is read on.
- *Draw the path on the cards, with a small call card floating over the canvas.*
  Chosen.

**Trade-offs.** The cards the call went through carry their step number, the
one it is in pulses, the ones not reached fade; the wires taken turn orange and
the edge that fired is tinted, with the values it collected on its field chips.
The call card holds what the graph cannot: the clock, the steps in order and the
transcript. The view is fitted once, into the space the card leaves, and does
not follow the call: the whole path stays in sight, and a step in the card
frames its node on demand.

The path is one pure reducer over the bot's `node` messages (`call/path.ts`),
so it is tested without a call and nothing in the browser infers a transition.
The transcript is in the same state: the caller's lines are the final
transcriptions, the agent's are the model's text as it is written, one line per
answer. That text is on screen a moment before it is heard and stays whole if
the caller cuts in; for reading a test that is the better side to err on.

The button is disabled, with the reason as its tooltip, while there are unsaved
changes or a warning: the call runs the saved agent, and a flow the checks say
a call cannot get through is not worth a call. While the call card is on
screen, running or ended, the editor is read-only: the path is drawn over this
very graph by node and edge name, and an edit would leave it pointing at what
changed. Closing the card gives the editor back.

Pipecat's JS client and its small WebRTC transport carry the call, the same
protocol as the prebuilt client; not the React bindings, since a handful of
callbacks into one reducer is all the editor needs. It is loaded when the first
call is placed, like ELK: it is 400 kB that most visits never use. A blocked
microphone, a start the backend refuses and a connection that fails each end as
a sentence in the call card, with Again next to it.

### The graph editor: React Flow, laid out and routed by ELK

**Context.** The deployment team has to read an agent's flow at a glance and
later edit it in place. A node can have several edges, and each one matters: it
is a tool the model calls, with its own condition and fields.

**Options.**
- *Canvas by hand (SVG).* Rejected: pan, zoom, drag and wires are most of an
  editor and none of the product.
- *React Flow with dagre for layout.* Rejected: dagre places boxes, not the
  points wires leave from, so the edges of one card cross on the way out.
- *React Flow, with ELK's layered layout and one port per edge.* Chosen.

**Trade-offs.** Each edge is a row of its card with its own dot, and ELK gets
that dot's real position as a fixed port, so wires leave in the order the rows
are read. That needs the cards' real sizes: the graph renders once out of sight,
is measured, then laid out and shown. ELK is 1.4 MB, loaded on first use.

The wires are drawn along ELK's own routes (right angles, rounded), not as
curves from dot to dot: a curve runs under whatever card is in between, and a
flow with a "go back" edge always has one. A route is only right for where the
cards were, so a wire whose ends no longer meet its route (its card was dragged)
falls back to a curve until "Tidy up". Columns are centered on one line rather
than placed to keep wires straight: with one dot per row, straight wires put
each card lower than the one before and a plain chain walks off the screen.

The card shows names as words ("Collect details" for `collect_details`) and
never an edge's function name: that is plumbing for the model, the condition is
what a person reads. The start node has no way in: a call begins there, so an
edge that names it is shown as not connected. Cards have an id of their own on
the canvas, because a name is text that will be edited and cannot also be the
card's identity; the agent JSON is untouched by it. The TypeScript types mirror
`schema.py` by hand, with the same field names: the API takes the agent as an
untyped object, so there is nothing to generate them from, and a schema change
has to be made in both places.

What is missing is drawn, not written: an edge with no target and a node nothing
leads to both end in a short dashed crimson stub, a wire that goes nowhere, so
the gap shows where it is. An edge that goes nowhere also stops a save, in
the editor, before anything is sent: the button then counts the loose wires and
frames them. A node nothing leads to is drawn the same way but saves: the
schema accepts it, and it is how a flow looks halfway through being built. A list of allowed values is a field type of its own,
Choice, though the agent JSON keeps it as a string with an `enum`: a type plus a
separate "only these values" asked for two decisions to say one thing. A node
with no way out and no end is where a call would stay for good, so its card asks
"What happens next?" and offers the two answers, move on to another step or end
the call here. The band that marks an end carries its own way back, next to
where it was chosen.

### Editing happens on a draft, changed by pure functions

**Context.** The editor changes an agent in many small steps (a word in a prompt,
a node made the start), several of which drag other things along, and all of it
has to be undoable. The backend only accepts an agent that is valid as a whole.

**Options.**
- *Let React Flow hold the graph and patch the agent from its events.* Rejected:
  two copies of the truth, and the rules (what a rename updates) end up spread
  over event handlers nobody can test.
- *A state library (Zustand, Redux).* Rejected for now: one agent open at a time
  and one screen reading it do not need one.
- *A draft in a reducer, edited by pure functions; React Flow only draws it.*
  Chosen.

**Trade-offs.** The draft is the agent JSON, an id per node and the card
positions by that id (they are stored by node name; keeping them by id is what
lets a rename carry the position). Each edit is a function from a draft to the next
(`draft/draft.ts`), so every rule is in one place with a test: renaming a node
updates the edges into it, its position and the agent's start; making a node the
start disconnects the edges into it; a deleted node leaves the edges into it
waiting for a target rather than deleting someone's condition. Fields the editor
does not show (`role_message`, pre and post actions, later task messages) pass
through untouched, so opening and saving never loses what the Copilot wrote.

Function names are generated, never typed or shown: `go_to_<target>`, numbered
when a node has two edges to the same place, regenerated when the target changes
or is renamed. They are the tool names the model sees, so they stay meaningful
without asking a deployment person to invent an identifier.

Changing the structure never runs the layout. A node added by hand goes where
it was dropped, or to the free spot nearest the middle of the view, and every
other card stays where someone put it; a new or retargeted wire is a plain curve
until "Tidy up", because ELK routes wires only as part of a full layout. The
start node takes no wire, in the draft and on the canvas, and a wire dropped
anywhere on a card connects to it.

Which card is on top is not part of the agent, so it is not in the draft: the
card last touched comes up and stays there, and its wires are highlighted, over
the other wires and under the cards like all of them. It is how the canvas is
being looked at, and undo and save never see it.

Saving sends the whole agent and its layout in one request, and the backend
stores both or neither. "Unsaved changes" is the draft not being the very one
that was loaded or last saved, so a save moves a marker and leaves undo alone,
and undoing back to the saved draft is clean again. When the backend refuses, its
422 carries the node's name and the edge's function as fields next to the
sentence: the editor marks that card and shows the sentence on it, without
reading names back out of text that may be reworded. The sentence is the
backend's own, so it is the one place a function name can reach the screen.

Saving is never blocked by unfinished work, only by what the backend refuses.
A node with no way out, a node no call can reach and a flow with no reachable
end are all valid agents, and they are what building one looks like, so they are
warnings: a quiet line on the card and a count next to Save. Running is what
they block. The checks are one pure function with the sentences in it
(`draft/checks.ts`), so the editor and whatever starts a call say the same thing
about the same draft. A loop is not a warning: some path has to end the call,
not every path.

Undo keeps whole drafts instead of inverse operations: an edit shares what it
does not touch with the draft before, so a snapshot is cheap and undo cannot
disagree with the edit. Typing in one field is one step. Cost: nothing is saved
until the save lands, and the browser's own undo inside a text field is replaced
by the editor's.

## How this was built

- Built with AI coding agents (Claude). `AGENTS.md` gives every coding agent the same context:
  goal, invariants, conventions and git workflow.
- Every change lands through a PR with CI (ruff) and an automated Claude review
  whose instructions are versioned in `.github/workflows/claude-review.yml`.
- PRs merge with merge commits, so the history shows how the work progressed.

## Demo

_The end-to-end walkthrough used in the review._

## Limitations and next steps

_Filled in at the end._
