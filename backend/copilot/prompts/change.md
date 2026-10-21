The work: make the change the person asked for, on a copy of the live
version.

If the pull request comes from a chat (the facts say what was asked), first
show the agent does not do it yet: reproduce, with a caller who needs what
was asked and checks that pass once the agent does it. A field or a step the
change would add can be named in a check only if the agent already has it;
otherwise check it with the one judged line. If it already passes, the person
is asked whether to go on, and your turn ends.

Then make the smallest change that does what they asked, and only that (a
rule on the step it is about, one step's task, one way on, one field), add a
test for it if none shows it, and run_all, with `said` saying what you
changed. When tests fail, decide as above; two rounds at most. If what they
wrote is a question, answer it and change nothing.
