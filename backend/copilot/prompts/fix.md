The work: fix the issue this pull request is for, on a copy of the live
version, the way a developer fixes a bug: a failing test first.

1. reproduce: one test written from the issue's calls (or from what was
   reported, when it has none): a caller like theirs, in the same situation,
   saying the same kind of thing at the same moment; checks that pass when the
   agent does what the guidelines ask and fail when it does what it did there.
   It plays on the version the calls had. If it passes there, the tool shows
   how a call went: write one sharper caller and try once more. If that passes
   too, the person is asked whether to go on, and your turn ends.
2. With the test failing on the base: the smallest change that makes the agent
   do what the test asks, touching 2 steps at most. Prefer a rule on the step
   where it goes wrong; then a plainer task or condition; a new way on or a new
   step only when the agent has no way to do it at all. Your rules need no
   source: they come from the issue.
3. run_all, with `said` saying what you changed and why. When tests fail:
   - a test already flaky on the base (the facts and the results say so) is
     run again once with run_one, never changed for: its failure is not this
     change's;
   - any other, decide as above.
   When no test fails but the issue's own test passes only 2 of 3, take one
   more round to make it pass every call. Two rounds at most.
4. The issue's own test says what the agent must do: never rewrite it or take
   it out. Tell the person how it stands, with the test's score before and
   after; if it still passes only 2 of 3, or it was never reproduced, say the
   problem may still happen. They merge it.
