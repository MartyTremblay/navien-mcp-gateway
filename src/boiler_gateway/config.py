"""Gateway settings, read from the environment or a `.env` file.

Secrets are typed as `SecretStr` so they never appear in reprs, logs or
error messages (P6). Names are listed in `.env.example`; values live only in
`.env` on the gateway host.
"""

from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Authorization server (ADR 0004, 0005)
    gateway_issuer: AnyHttpUrl = Field(description="Keycloak realm issuer URL")
    gateway_resource_url: AnyHttpUrl = Field(
        description="The gateway's canonical MCP URL; tokens must carry it as `aud`"
    )
    gateway_token_algorithms: list[str] = Field(default=["RS256"])
    gateway_jwks_cache_seconds: int = Field(default=300, ge=0)

    # Transport (ADR 0003)
    gateway_bind_host: str = Field(default="127.0.0.1")
    gateway_port: int = Field(default=8080, ge=1, le=65535)
    gateway_allowed_origins: list[str] = Field(default_factory=list)

    # Audit (ADR 0007)
    gateway_audit_db: Path = Field(default=Path("data/audit.sqlite"))

    # Device (ESPHome native API, Noise-encrypted)
    esphome_host: str
    esphome_port: int = Field(default=6053, ge=1, le=65535)
    esphome_noise_psk: SecretStr

    @field_validator("gateway_resource_url")
    @classmethod
    def _resource_is_canonical(cls, v: AnyHttpUrl) -> AnyHttpUrl:
        # MCP authorization spec: canonical URI, https, no fragment, no trailing slash.
        text = str(v)
        if v.scheme != "https":
            raise ValueError("resource URL must use https")
        if v.fragment:
            raise ValueError("resource URL must not contain a fragment")
        if text.endswith("/"):
            raise ValueError("resource URL must not end with a slash")
        return v

    @property
    def issuer(self) -> str:
        return str(self.gateway_issuer).rstrip("/")

    @property
    def resource_url(self) -> str:
        return str(self.gateway_resource_url)
