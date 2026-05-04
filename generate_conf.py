#!/usr/bin/env python3

import os
import sys
import shutil

from parsing import parse_intent
from addressing import allocate_addresses
from bgp import build_bgp_fullmesh, build_vpnv4_fullmesh, build_inter_as_neighbors
from generators.config import generate_router_config


def main(intent_path: str) -> None:
    as_map = parse_intent(intent_path)

    if os.path.exists("configs_final"):
        shutil.rmtree("configs_final")
    os.makedirs("configs_final", exist_ok=True)

    allocate_addresses(as_map)
    build_bgp_fullmesh(as_map)
    build_vpnv4_fullmesh(as_map)
    build_inter_as_neighbors(as_map)

    for as_obj in as_map.values():
        for router in as_obj.routers.values():
            cfg = generate_router_config(router, as_obj)
            fname = f"configs_final/i{router.number}_startup-config.cfg"
            with open(fname, "w") as f:
                f.write(cfg)
            print(f"Generated {fname}")

    print("\n=== Address Summary ===")
    for as_obj in as_map.values():
        print(f"\n{as_obj.name} (IPv{as_obj.ip_version}, {as_obj.protocol}):")
        for router in as_obj.routers.values():
            lo_len = router.loopback_prefix_len_v4 if as_obj.ip_version == 4 else 128
            print(f"  {router.name:<6}  Lo0: {router.loopback}/{lo_len}")
            for iface in router.interfaces.values():
                print(f"         {iface.name}: {iface.ip}/{iface.prefix_len}")


if __name__ == "__main__":
    intent_path = sys.argv[1] if len(sys.argv) > 1 else "intent_vrf.json"
    main(intent_path)
