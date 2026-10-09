import pytest
from pydantic import ValidationError

from boiler_gateway.config import Settings

BASE = {
    "gateway_issuer": "https://auth.lab.example.org/realms/home",
    "gateway_resource_url": "https://boiler.lab.example.org/mcp",
    "esphome_host": "192.0.2.10",
    "esphome_noise_psk": "dGVzdC1rZXktbm90LXJlYWwtMDAwMDAwMDAwMDAwMA==",
}


def make(**overrides):
    return Settings(_env_file=None, **{**BASE, **overrides})


def test_defaults_are_safe():
    s = make()
    assert s.gateway_bind_host == "127.0.0.1"  # ADR 0003: localhost unless told otherwise
    assert s.gateway_allowed_origins == []
    assert s.gateway_token_algorithms == ["RS256"]


def test_secret_never_appears_in_repr_or_str():
    s = make()
    assert BASE["esphome_noise_psk"] not in repr(s)
    assert BASE["esphome_noise_psk"] not in str(s)
    assert s.esphome_noise_psk.get_secret_value() == BASE["esphome_noise_psk"]


def test_issuer_has_no_trailing_slash():
    assert make(gateway_issuer="https://auth.lab.example.org/realms/home/").issuer == (
        "https://auth.lab.example.org/realms/home"
    )


@pytest.mark.parametrize(
    "bad",
    [
        "http://boiler.lab.example.org/mcp",
        "https://boiler.lab.example.org/mcp/",
        "https://boiler.lab.example.org/mcp#frag",
    ],
)
def test_resource_url_must_be_canonical(bad):
    with pytest.raises(ValidationError):
        make(gateway_resource_url=bad)


def test_missing_device_key_is_an_error():
    args = {k: v for k, v in BASE.items() if k != "esphome_noise_psk"}
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **args)
