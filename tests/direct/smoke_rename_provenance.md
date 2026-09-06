# Smoke rename provenance notes

Second rename-evidence artifact for the CommitScopeEscrow boundary-fix
smoke (Studionet). This file starts OUTSIDE the smoke deal's allowed
paths (docs/) and is then moved INTO them (tests/direct/) with a real
`git mv`, so the GitHub compare API reports:

    filename:          tests/direct/smoke_rename_provenance.md
    status:            renamed
    previous_filename: docs/smoke_rename_provenance.md

The previous (source) path lies outside allowed_paths=tests/, so the
fixed diff_scope gate must FAIL the deal and cite the source path -
proving an out-of-scope source cannot vanish via a rename into scope.
