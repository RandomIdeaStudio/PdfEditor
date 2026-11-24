# Security & Code Signing Policy

## Reporting a Vulnerability
If you discover a security vulnerability (for example, related to redaction or file handling), please open a private security advisory on GitHub or write to randomideastudio.dev@gmail.com before public disclosure.

## Privacy
PDF Editor runs 100% locally on the user's machine. It makes no network connections, collects no telemetry, and never uploads user documents. See [PRIVACY.md](PRIVACY.md).

## Code signing policy
Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by [SignPath Foundation](https://signpath.org).

- Committers and reviewers: [RandomIdeaStudio](https://github.com/RandomIdeaStudio)
- Approvers: [RandomIdeaStudio](https://github.com/RandomIdeaStudio)
- Signed binaries are built in GitHub Actions (`.github/workflows/ci.yml`, inputs `build_exe` and `sign`) from tagged commits on `main`, on GitHub-hosted runners only.
- Every signing request is approved manually by an approver. Only this project's own binaries are signed, never third-party programs.
- All team members use multi-factor authentication for GitHub and SignPath.
