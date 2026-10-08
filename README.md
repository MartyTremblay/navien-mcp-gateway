# navien-mcp-gateway

A governed MCP server in front of an ESPHome-controlled Navien boiler: authentication, per-tool authorization, policy on writes, and audit logging between AI clients and the device.

A learning project for enterprise AI architecture patterns. See [CLAUDE.md](CLAUDE.md) for goals, safety rules and open decisions.

## Why this project exists

Most enterprise AI governance is written as policy: principles, review boards, risk registers. The harder question is what that policy looks like when an AI agent is allowed to act on a real system. This project works through that question at small scale.

A home boiler stands in for an enterprise system of record. It is a real device with real consequences (a gas appliance in an occupied house), but it has one owner and a small blast radius, so every control can be built and tested end to end. The AI agent never talks to the device directly. Every request goes through a gateway that does what an enterprise control plane would:

- **Identity:** every client authenticates, and the agent has its own identity rather than borrowed human credentials.
- **Authorization:** least privilege per tool, using scopes such as `boiler:read` and `boiler:write`.
- **Policy:** hard value bounds, rate limits, and human approval for high-risk actions.
- **Audit:** every call is recorded with who, which tool, arguments, policy decision, result and latency.
- **Secret isolation:** device credentials stay on the server and are never exposed to clients.

The reasoning matters as much as the code. Each design choice is recorded as an [architecture decision record](docs/adr/). A threat model covering prompt injection, over-broad tools and stolen client tokens is planned, and the controls will be mapped to the NIST AI Risk Management Framework and ISO/IEC 42001, so the path from framework to working control is explicit.

Status: planning.

## How it's built

This project is vibe coded: the code, ADR drafts and documentation are written with [Claude Code](https://claude.com/claude-code), an AI coding agent, and commits it co-authored carry a `Co-Authored-By: Claude` trailer. That is part of the experiment. An AI agent helping build a governed path for AI agents is a small version of the question enterprises now face about their own delivery teams.

The agent works under the same kind of guardrails the gateway enforces. Its standing instructions are in [CLAUDE.md](CLAUDE.md): safety rules for the device, hard bounds, no secrets in the repo, plan before structural changes, small reviewable commits, and verification against the real device before anything is called done. Architecture decisions, risk tolerance and anything touching the boiler's safety stay with the human.

## Author

Built by Marty Tremblay, enterprise architect at [Aspiro Consulting](https://www.aspiroconsulting.ca/).
