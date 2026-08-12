# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.7.x   | Yes |
| 0.6.x   | Best-effort |
| < 0.6   | No |

## What to report

Please report vulnerabilities that affect:

- Study integrity seals (false verify / silent seal bypass)
- Plugin trust gates
- Report generation (XSS / claim-lint bypass)
- Release / CI supply chain for this repository

Do **not** use the public issue tracker for unfixed security issues.

## How to report

Email the maintainer via GitHub: [@taipei49314](https://github.com/taipei49314)  
Prefer a private GitHub Security Advisory on this repo when available.

Include:

1. Affected version / commit
2. Impact (integrity, RCE in-process via plugin, XSS, supply chain)
3. Minimal reproduction (local study mutation is fine; no public exploit dump required)

## Threat model pointer

See [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md). Full local rewrite of every seal (adversary A5) is a **documented residual** until M4 — reports that only restate A5 are not treated as new vulnerabilities unless they bypass M1 checks for *inconsistent* edits.

## Disclosure

We aim to acknowledge within 7 days and ship a fix or mitigation advisory for confirmed M1/M3 issues in a timely patch release.
