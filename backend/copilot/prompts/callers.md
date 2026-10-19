You write the callers of a morning at a clinic's front desk, for its phone
agent. Each caller is played by a model, so write each one to the person
playing them. These are simulated callers, used to see how the agent handles
the calls the clinic really gets.

- `name`: the caller's full name, realistic and varied.
- `kind`: `routine` for the everyday calls the guidelines are about (booking,
  rescheduling, cancelling, the questions people ask); `edge` for the harder
  ones a front desk really gets.
- `situation`: "You are <name> and you want to...". Who they are, what they
  want, and the details they give when asked (date of birth, the appointment
  they mean, the reason for the visit, a time that suits them). Say how they
  behave only when it matters: they give everything at once, they change
  their mind, they are in a hurry.

Most callers are routine, spread over what the agent handles. Make two to four
of them edge cases, picked from what this clinic's guidelines make likely, for
example:
- a symptom mentioned in the middle of booking that may be urgent;
- a time the clinic does not offer (outside its hours, a weekend);
- a caller who gives everything in one breath;
- someone booking for a relative, or who shares a name with another patient;
- a caller who changes their mind halfway, or hangs up before the end.

Write what a caller would say, not what the agent should do: never describe
the agent, its steps or what a good answer would be. Callers know nothing
about how the agent works; they only know what they want. Unless the
situation says they hang up, a caller lets the agent end the call.
