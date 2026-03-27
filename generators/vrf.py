def render_vrf(topology: dict, router_name: str) -> list[str]:
    router = topology["routers"][router_name]

    if router["role"] != "PE":
        return []

    lines = ["! ===== VRF CONFIG ====="]

    used_vrfs = set()
    for link in topology["links"]:
        if link.get("vrf") and (link["a"] == router_name or link["b"] == router_name):
            used_vrfs.add(link["vrf"])

    for vrf_name in used_vrfs:
        vrf = topology["vrfs"][vrf_name]

        lines.append(f"ip vrf {vrf_name}")
        lines.append(f" rd {vrf['rd'][router_name]}")

        for rt in vrf["rt_export"]:
            lines.append(f" route-target export {rt}")
        for rt in vrf["rt_import"]:
            lines.append(f" route-target import {rt}")

        lines.append("!")

    return lines

def render_vrf_interfaces(topology: dict, router_name: str) -> list[str]:
    router = topology["routers"][router_name]

    if router["role"] != "PE":
        return []

    lines = ["! ===== VRF INTERFACES ====="]

    for link in topology["links"]:
        if not link.get("vrf"):
            continue

        if link["a"] == router_name:
            lines.append(f"interface {link['a_if']}")
            lines.append(f" ip vrf forwarding {link['vrf']}")
            lines.append("!")
        elif link["b"] == router_name:
            lines.append(f"interface {link['b_if']}")
            lines.append(f" ip vrf forwarding {link['vrf']}")
            lines.append("!")

    return lines