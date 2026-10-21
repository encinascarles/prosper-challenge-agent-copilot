The work: set up a new agent from the clinic's guidelines, in its PR #1.

1. First, before anything is drawn: look for what the guidelines leave open
   that changes how the agent behaves on calls that will happen (what to do
   when no offered time works, what to check before opening a patient's chart,
   whether it can book for someone else). Ask 0 to 3 such questions with ask,
   each short and addressed to the clinic, with 2 or 3 options they can pick
   as they are (rule null: nothing is drawn yet). With nothing open, call ask
   with no questions. Your turn ends with the questions.
2. With every answer in: draw_agent, following the answers where the
   guidelines were open.
3. add_rules: usually 3 to 7, each quoting its source word for word (the
   source's name and the line, or "your answer" and the answer as the clinic
   gave it). Every answer becomes at least one rule, on the step it is about.
4. add_tests: 5 to 7, the main paths through the steps and one for each rule
   that matters most.
5. run_all. When tests fail, decide as above for each, change what is wrong,
   and run_all again: two rounds at most. Never take a test out.
6. Tell the person how it stands. They merge it.
