# navien-mcp-gateway

A governed [Model Context Protocol](https://modelcontextprotocol.io) (MCP) gateway between AI agents and a real device: an ESPHome-controlled Navien boiler. Every request is authenticated, authorized per tool, checked against policy and audited before anything reaches the boiler.

It's a learning project in enterprise AI governance: practising, end to end and on real equipment, the controls an enterprise would put between AI agents and a system of record.

![Architecture: the AI agent and the owner's browser on the household network reach a separate lab network only through the router's allow list. In the lab, a reverse proxy fronts the MCP gateway and Keycloak; the gateway validates tokens, records every decision in a hash-chained audit store, and is the only lab component allowed to reach the boiler controller. Home Assistant keeps its own path.](docs/images/architecture.svg)

## Why this project exists

Most enterprise AI governance is written as policy: principles, review boards, risk registers. The harder question is what that policy looks like when an AI agent is allowed to act on a real system. This project works through that question at small scale.

A home boiler stands in for an enterprise system of record. It is a real device with real consequences (a gas appliance in an occupied house), but it has one owner and a small blast radius, so every control can be built and tested end to end. The AI agent never talks to the device directly. Every request goes through a gateway that does what an enterprise control plane would:

- **Identity:** every client authenticates through an identity provider, and each token names both the person who granted access and the agent acting for them.
- **Authorization:** least privilege per tool, with scopes such as `boiler:read` and `boiler:write`; tokens are bound to this gateway and refused anywhere else.
- **Policy:** gateway-side bounds and rate limits on writes, and human approval for high-risk actions (planned).
- **Audit:** every request, including every refusal, is recorded in a tamper-evident log before anything happens.
- **Isolation:** the gateway runs on a separate lab network, behind its own reverse proxy; the device's key never leaves the gateway.

The reasoning matters as much as the code. Every significant choice is an [architecture decision record](docs/adr/), threats are tracked with the evidence that their controls work, and each increment ends with a compliance check.

## Status

| Increment | What | Status |
|---|---|---|
| 1 | Read-only gateway: one status tool, identity, isolation, audit | Done and deployed; [compliance check](docs/compliance/increment-1.md) passed |
| 2 | First bounded write: hot-water tank setpoint | Built and tested ([ADR 0008](docs/adr/0008-write-policy-for-bounded-setpoints.md)); writes switched off until the first supervised live test |
| 3 | Second write, policy as versioned configuration | Planned |
| 4 | Human approval for high-risk actions | Planned |
| 5 | Hardening and evidence, including a NIST AI RMF mapping | Planned |

Details in the [roadmap](docs/architecture/03-roadmap.md).

## Where to start reading

1. **[The request path](docs/images/request-path.svg):** the seven layers every request passes through, and what happens when one fails.
2. **[Principles](docs/architecture/00-principles.md)** and **[vision](docs/architecture/01-vision.md):** what the gateway must guarantee, and why.
3. **[Architecture decision records](docs/adr/):** the choices, the options considered, and the trade-offs, including where reality changed the plan.
4. **[Threat model](docs/threat-model.md):** threats, controls and evidence, plus lessons from real incidents during the build.
5. **[Compliance check, increment 1](docs/compliance/increment-1.md):** the end-of-increment review against the principles.
6. **[Frameworks and standards](docs/standards.md):** the 39 frameworks, standards and specifications the project relies on, and where each applies.

The method is a lightweight version of the TOGAF Architecture Development Method; the [architecture index](docs/architecture/README.md) maps each phase to its document.

## Where it came from

The boiler is reachable at all thanks to a community project, [htumanyan/navien](https://github.com/htumanyan/navien), which lets an ESP32 board running ESPHome talk to Navien boilers through their NaviLink port. Support for the board and boiler model used here was contributed to that project by the author. This repository builds the governed path for AI agents on top of it.

## Safety

This software can change settings on a gas appliance. It's published as a worked example of governance patterns, not as a product. If you adapt it, keep the gateway's bounds, read-back and kill switch, test against a fake device first, and make any live change with someone watching. The [MIT licence](LICENSE) applies, including its "as is" terms.

## How it's built

This project is AI-assisted (sometimes called vibe coding): the code, ADR drafts and documentation are written with [Claude Code](https://claude.com/claude-code), an AI coding agent, and commits it co-authored carry a `Co-Authored-By: Claude` trailer. That is part of the experiment. An AI agent helping build a governed path for AI agents is a small version of the question enterprises now face about their own delivery teams.

The agent works under the same kind of guardrails the gateway enforces. Its standing instructions are in [CLAUDE.md](CLAUDE.md): safety rules for the device, hard bounds, no secrets in the repo, plan before structural changes, small reviewable commits, and verification against the real device before anything is called done. Architecture decisions, risk tolerance and anything touching the boiler's safety stay with the human.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

Direct dependencies are pinned in `pyproject.toml`; `requirements.lock` records the full resolved set. Configuration comes from environment variables or a `.env` file; `.env.example` lists the names. Writes are off unless `GATEWAY_WRITES_ENABLED=true`.

## Author

Built by Marty Tremblay, enterprise architect at [Aspiro Consulting](https://www.aspiroconsulting.ca/).
