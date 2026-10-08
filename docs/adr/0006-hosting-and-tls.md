# 0006. Hosting and TLS on the local network

Status: accepted (2026-10-08)

Principles: applies P1 (least privilege, here for infrastructure credentials), P6 (secrets stay server-side), P7 (fail safe) and P9 (do not disrupt existing systems).

## Context

[ADR 0003](0003-streamable-http-transport.md) allows the gateway on the local network only behind TLS, and never on the internet. [ADR 0005](0005-keycloak-identity-provider.md) requires HTTPS for Keycloak. Both need certificates that MCP clients trust without extra setup.

The existing lab provides:

- a Proxmox host for containers;
- **Zoraxy**, a reverse proxy that obtains Let's Encrypt certificates through the lego library, including DNS challenges;
- **AdGuard Home** as the local DNS resolver;
- public DNS for the owner's domain at a cPanel-based hosting provider. lego has a `cpanel` provider.

Home Assistant's remote access goes through Nabu Casa and is not affected (P9).

The standard way to get publicly trusted certificates for names that are not reachable from the internet is the ACME DNS-01 challenge: the certificate tooling proves control of the domain by writing a TXT record, so no inbound port is needed. The cost is that the tooling holds a credential that can change DNS records.

## Options considered

1. **Delegate a lab subdomain to deSEC.** Add NS records at the current DNS host that delegate `lab.<domain>` to deSEC, a free DNS host with an API, run by the Berlin-based non-profit deSEC e.V. and funded by donations and sponsors, and let Zoraxy complete DNS challenges there. deSEC tokens "can be restricted using Token Policies, which narrow down the scope of influence for a given API token" by domain, subname and record type, can be limited to source addresses with `allowed_subnets`, and by default cannot create domains or manage tokens ([deSEC token docs](https://desec.readthedocs.io/en/latest/auth/tokens.html)). lego has a `desec` provider.
2. **Use the cPanel API on the main domain.** No new services, but the token sits on the reverse proxy and can likely change much more than one TXT record: every DNS record for the domain, including email records, and possibly other parts of the hosting account. That is too broad a credential for this job.
3. **Run a private certificate authority** (for example step-ca on Proxmox). This is the closest to enterprise PKI, but every client needs the root certificate installed, and the operating system, Python and Node each keep their own trust store. That is a lot of friction for MCP clients.
4. **Move the whole domain's DNS to a provider with zone-scoped tokens.** This means migrating email and every other record to solve a lab problem.

## Decision

Option 1, delegating `lab.<domain>` to deSEC, with this layout:

**Hosting**

- The gateway runs in its own Proxmox LXC container. The device key exists only there.
- Keycloak runs in a separate LXC container with its PostgreSQL database (ADR 0005).
- Zoraxy terminates TLS for both and forwards to the containers on the Proxmox bridge.

**Names and certificates**

- Service names live under `lab.<domain>`, for example `auth.lab.<domain>` for Keycloak and `boiler.lab.<domain>` for the gateway.
- Zoraxy obtains one wildcard certificate, `*.lab.<domain>`, through deSEC. A wildcard keeps individual service names out of the public Certificate Transparency logs, where every Let's Encrypt certificate is published.
- The deSEC token used by Zoraxy is restricted to TXT records at `_acme-challenge` names under the lab subdomain, with no permission to create or delete domains or manage tokens.

**Name resolution**

- AdGuard Home rewrites the lab names to Zoraxy's local address. No public DNS records point at private addresses.

**Network controls**

- In the containers, the gateway and Keycloak listen on their container address rather than localhost, because Zoraxy has to reach them. To make up for that, the Proxmox firewall on each container accepts connections on the service port only from Zoraxy. A client on the local network cannot skip TLS by connecting to the container directly.
- Zoraxy is not reachable from the internet. If that ever changes, the lab hosts must first be restricted to local source addresses in Zoraxy, or a request to the public address with a lab `Host` header could reach them.

**Fallback**

- If deSEC does not accept a subdomain of a domain registered elsewhere, use acme-dns delegation instead: a CNAME for each `_acme-challenge` name pointing to an acme-dns service, whose credential can only update that one TXT record.

## Consequences

- Certificates are publicly trusted, so MCP clients, Python and Node work without installing a custom root certificate.
- No inbound ports are opened for the gateway or Keycloak, in keeping with ADR 0003.
- **Zoraxy sees bearer tokens.** It terminates TLS, so access tokens pass through it in clear text and travel unencrypted over the Proxmox bridge to the containers. This is normal for TLS-terminating ingress in an enterprise. It is accepted here because the bridge is internal, the firewall allows only Zoraxy, and tokens live for 5 minutes. Zoraxy and its logs must not record `Authorization` headers.
- **Data location.** The lab subdomain's public DNS is hosted in Germany. It holds only public records (the zone itself and short-lived `_acme-challenge` TXT records). Local names resolve through AdGuard Home and never reach deSEC.
- **Provider continuity.** deSEC depends on donations. If it stops operating, the acme-dns fallback above replaces it. Only renewals are affected, so there is up to 90 days to switch.
- **DNSSEC.** deSEC signs the lab zone automatically. Delegation works whether or not the main domain is signed. If the main domain is signed later, deSEC's DS record must be added at the current DNS host.
- **ADR 0003 refinement.** "Bind to localhost by default" still applies to development. In the deployed containers, the firewall rule replaces it.
- **New dependencies.** deSEC and Let's Encrypt are needed only to renew certificates, which last 90 days, so a short outage of either has no effect. AdGuard Home becomes necessary for clients to find the services. If it is down, names stop resolving and calls fail closed (P7).
- **Configuration to verify during setup:**
  - Keycloak behind a proxy needs its public hostname and forwarded-header settings, or tokens will carry the wrong issuer and the gateway will reject them.
  - The MCP spec asks servers to send `X-Accel-Buffering: no` on SSE streams so proxies don't buffer them. Whether Zoraxy buffers SSE responses must be tested.
- The domain's real name stays out of this repository. Hostnames are written as `lab.<domain>`, with the actual values in local configuration.
