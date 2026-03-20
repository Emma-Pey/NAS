def render_mpls_ldp(topology: dict, router_name: str) -> list[str]:
    router = topology["routers"][router_name]

    if router["role"] not in {"PE", "P"}:
        return []

    lines = []


    has_mpls = False
    for link in topology["links"]:
        if (link["a"] == router_name or link["b"] == router_name) and link.get("mpls"):
            has_mpls = True
            break

    if not has_mpls:
        return []

    lines.append("! ===== MPLS / LDP =====")
    lines.append("mpls label protocol ldp")
    lines.append("mpls ldp router-id Loopback0 force")
    lines.append("!")

    for link in topology["links"]:
        if not link.get("mpls"):
            continue

        if link["a"] == router_name:
            lines.append(f"interface {link['a_if']}")
            lines.append(" mpls ip")
            lines.append("!")
        elif link["b"] == router_name:
            lines.append(f"interface {link['b_if']}")
            lines.append(" mpls ip")
            lines.append("!")

    return lines