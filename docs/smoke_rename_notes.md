# Smoke rename-evidence notes

This file exists to produce a REAL `git mv` rename entry in the GitHub
compare API payload (status="renamed" with previous_filename) for the
CommitScopeEscrow boundary-fix smoke test on Studionet.

See SUBMISSION_DRAFT.md "Boundary-case fixes (steward review round)"
for the two rename scenarios this evidence serves:

- S5 rename in-scope -> in-scope (both paths inside allowed_paths)
  must stay Released;
- S6 rename out-of-scope -> in-scope (source path outside
  allowed_paths) must stay Rejected with the source path cited.

The contract validates BOTH sides of every rename; this file is the
in-repo artifact whose path history demonstrates it live.
