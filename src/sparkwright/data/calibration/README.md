# Calibration suite (SYSTEM S10.1)

Each file in `cases/` is a review context with one planted flaw (or none, for
`clean-*` controls). Front matter: `expect` lists the personas that should
catch it, `ids` the requirement IDs involved, `keywords` alternative evidence
that a finding is about the flaw. A persona catches a case when it raises a
high- or medium-severity finding that cites one of `ids` or mentions one of
`keywords`. A high-severity finding on a clean control is a false alarm.

The cases describe an invented fitness-studio booking app. Add cases freely;
keep each to one flaw.
