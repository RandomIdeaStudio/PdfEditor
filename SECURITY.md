# Security & Code Signing Policy

## Reporting a Vulnerability
If you discover a security vulnerability (for example, related to redaction or file handling), please open a private security advisory on GitHub or contact the maintainer directly before public disclosure.

## Privacy
PdfEditor runs 100% locally on the user's machine. It makes no network connections, collects no telemetry, and never uploads user documents.

## Code Signing Policy
- Official Windows release binaries are built reproducibly in GitHub Actions from tagged commits on `main`.
- Free code signing is intended to be provided by [SignPath.io](https://signpath.io/), with a certificate by the [SignPath Foundation](https://signpath.org/).
- Only repository maintainers listed as committers/approvers may trigger release builds and approve signing requests.
