#!/usr/bin/env python3
"""Read-only look at the ESPHome device: identity, entities and current states.

Connects with the settings in `.env` (ESPHOME_HOST, ESPHOME_PORT,
ESPHOME_NOISE_PSK), lists entities, collects state updates for a few seconds,
then disconnects. It sends no commands: only the device-info, list-entities
and subscribe-states requests. The encryption key is never printed.

    .venv/bin/python tools/device_inspect.py [--seconds 8] [--json]
"""

import argparse
import asyncio
import json
import sys

from aioesphomeapi import APIClient

from boiler_gateway.config import DeviceSettings


async def inspect(seconds: float) -> dict:
    cfg = DeviceSettings()
    client = APIClient(
        cfg.esphome_host,
        cfg.esphome_port,
        noise_psk=cfg.esphome_noise_psk.get_secret_value(),
        client_info="boiler-gateway-inspect",
    )
    await client.connect(login=True)
    try:
        info, entities, _services = await client.device_info_and_list_entities()
        states: dict[int, object] = {}
        client.subscribe_states(lambda st: states.__setitem__(st.key, st))
        await asyncio.sleep(seconds)
    finally:
        await client.disconnect()

    rows = []
    for e in sorted(entities, key=lambda e: (type(e).__name__, e.object_id)):
        st = states.get(e.key)
        value = None
        if st is not None:
            for attr in ("state", "current_temperature", "target_temperature"):
                if hasattr(st, attr):
                    value = getattr(st, attr)
                    break
            if getattr(st, "missing_state", False):
                value = None
        rows.append(
            {
                "type": type(e).__name__.removesuffix("Info"),
                "object_id": e.object_id,
                "name": e.name,
                "unit": getattr(e, "unit_of_measurement", "") or "",
                "category": str(getattr(e, "entity_category", "") or "").split(".")[-1],
                "value": value if not isinstance(value, float) else round(value, 2),
            }
        )
    return {
        "device": {
            "name": info.name,
            "esphome_version": info.esphome_version,
            "project": f"{info.project_name} {info.project_version}".strip(),
        },
        "entities": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--seconds", type=float, default=8.0, help="how long to collect state updates")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = ap.parse_args()

    result = asyncio.run(inspect(args.seconds))
    if args.json:
        json.dump(result, sys.stdout, indent=2, default=str)
        print()
        return 0
    d = result["device"]
    print(f"Device: {d['name']}  ESPHome {d['esphome_version']}  {d['project']}")
    print(f"{'TYPE':<16} {'OBJECT_ID':<40} {'VALUE':>12} {'UNIT':<6} NAME")
    for r in result["entities"]:
        print(
            f"{r['type']:<16} {r['object_id']:<40} {r['value']!s:>12} {r['unit']:<6} "
            f"{r['name']}{'  [' + r['category'] + ']' if r['category'] not in ('', 'none') else ''}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
