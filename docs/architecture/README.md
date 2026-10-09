# Architecture

This project follows a lightweight version of the TOGAF Architecture Development Method (ADM). Each phase is scaled down to what one device and one household need. The phases are used for traceability, not for paperwork.

| ADM phase | Artifact | Status |
|---|---|---|
| Preliminary | [Architecture principles](00-principles.md) | Draft |
| A. Architecture Vision | [Architecture vision](01-vision.md) | Draft |
| B, C, D. Business, Data/Application, Technology | [Baseline and target architecture](02-baseline-target.md) | Draft |
| E, F. Opportunities and Migration | [Roadmap of increments](03-roadmap.md) | Draft |
| G. Implementation Governance | Compliance check at the end of each increment ([defined in the roadmap](03-roadmap.md#implementation-governance-phase-g)) | Defined |
| H. Change Management | New ADRs that supersede old ones | Ongoing |
| Requirements Management | Requirements register tracing requirement → threat → control → NIST AI RMF function | Planned |

Decisions made along the way are recorded as [ADRs](../adr/). Each ADR should name the principles it applies or trades off.

Deliberately left out: the full content metamodel, an architecture repository, capability-based planning and detailed business architecture. At this scale they would add documents without adding insight.
