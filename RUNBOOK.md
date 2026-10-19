# Source and release operations

Use the behavior spec and operator runbook under specs/ and docs/runbooks/. All source changes use a task branch and PR to main, required CI, and qualified non-author human review. No direct main update, forced history rewrite or collaborator grant is part of a release.

This public repository has fresh selected history. The separately accepted v0.1.0 package/build files are bound by their release checksums; release administration files added here are outside the frozen package selection. Preserve those bytes rather than rebuilding a substitute. Installation does not adopt the tool into an estate runtime.
