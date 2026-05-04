import json
import ipaddress
from typing import Dict

from models import AutonomousSystem, Router, Neighbor, Interface


def parse_intent(path: str) -> Dict[str, AutonomousSystem]:
    with open(path) as f:
        data = json.load(f)
    as_map: Dict[str, AutonomousSystem] = {}

    for as_data in data["autonomous_systems"]:
        addr = as_data["addressing"]

        if "ipv6_prefix" in addr:
            ip_version = 6
            ipv6_prefix = ipaddress.IPv6Network(addr["ipv6_prefix"])
            loopback_pool = ipaddress.IPv6Network(addr["loopback_pool"])
            link_pool = ipaddress.IPv6Network(addr["link_pool"])
            inter_as_pool = ipaddress.IPv6Network(data["bgp"]["inter_as_link_pool"]) if "bgp" in data else None
        else:
            ip_version = 4
            ipv6_prefix = None
            loopback_pool = ipaddress.IPv4Network(addr["loopback_pool"])
            link_pool = ipaddress.IPv4Network(addr["link_pool"])
            inter_as_pool = ipaddress.IPv4Network(data.get("bgp", {}).get("inter_as_link_pool")) if "bgp" in data else None

        as_obj = AutonomousSystem(
            name=as_data["name"],
            asn=as_data["asn"],
            ip_version=ip_version,
            ipv6_prefix=ipv6_prefix,
            loopback_pool=loopback_pool,
            link_pool=link_pool,
            inter_as_link_pool=inter_as_pool,
            protocol=as_data.get("routing", {}).get("protocol"),
            process_id=as_data.get("routing", {}).get("process_id"),
            area=as_data.get("routing", {}).get("area"),
            ospf_style=as_data.get("routing", {}).get("ospf_style", "network"),
            ios_legacy_defaults=as_data.get("ios_legacy_defaults", False),
            mpls=as_data.get("mpls", False),
            rsvp=as_data.get("rsvp", False),
            allow_as_in=as_data.get("bgp", {}).get("allow-as in", False),
        )

        for rdata in as_data["routers"]:
            router = Router(
                name=rdata["name"],
                number=rdata.get("number", 0),
                role=rdata["role"],
                asn=rdata.get("router_asn", as_obj.asn),
                neighbors=[Neighbor(**n) for n in rdata.get("neighbors", [])],
                route_reflector=(
                    rdata.get("route_reflector", False)
                    or rdata.get("route-reflector", False)
                    or rdata.get("route reflector", False)
                ),
                other_interfaces=rdata.get("other_interfaces", {}),
                internet_gateway=rdata.get("internet_gateway", False),
            )

            vrf_definitions = {v["name"]: v for v in as_data.get("vrfs", [])}

            for neighbor in router.neighbors:
                if hasattr(neighbor, "vrf") and neighbor.vrf:
                    v_name = neighbor.vrf
                    router.interface_vrf_map[neighbor.interface] = v_name
                    if v_name in vrf_definitions:
                        v_def = vrf_definitions[v_name]
                        router.vrfs[v_name] = {
                            "rd": f"{as_obj.asn}:{int(v_def.get('rd_base', 0))}",
                            "rt_import": v_def.get("rt_import", []),
                            "rt_export": v_def.get("rt_export", []),
                        }

            for vrf_entry in rdata.get("vrfs", []):
                v_name = vrf_entry["name"]
                if v_name not in router.vrfs:
                    router.vrfs[v_name] = {
                        "rd": vrf_entry["rd"],
                        "rt_import": vrf_entry.get("rt_import", []),
                        "rt_export": vrf_entry.get("rt_export", []),
                    }

            for iface_name, vrf_name in rdata.get("interface_vrf_map", {}).items():
                router.interface_vrf_map[iface_name] = vrf_name

            for vpn_peer in rdata.get("bgp_vpnv4_neighbors", []):
                v_ip = vpn_peer["ip"]
                router.bgp_vpnv4_neighbors[v_ip] = {
                    "asn": vpn_peer["asn"],
                    "activate": vpn_peer.get("activate", True),
                    "send_community_extended": vpn_peer.get("send_community_extended", True),
                }
                if v_ip not in router.bgp_neighbors:
                    router.bgp_neighbors[v_ip] = vpn_peer["asn"]

            for vrf_peer in rdata.get("vrf_bgp_neighbors", []):
                v_name = vrf_peer["vrf"]
                router.vrf_bgp_neighbors.setdefault(v_name, []).append({
                    "ip": vrf_peer["ip"],
                    "asn": vrf_peer["asn"],
                    "activate": vrf_peer.get("activate", True),
                })

            for iface_data in rdata.get("static_interfaces", []):
                router.interfaces[iface_data["name"]] = Interface(
                    name=iface_data["name"],
                    ip=ipaddress.ip_address(iface_data["ip"]),
                    prefix_len=iface_data["prefix_len"],
                    ospf_area=iface_data.get("ospf_area"),
                    ospf_cost=iface_data.get("ospf_cost"),
                )

            as_obj.routers[router.name] = router

        as_map[as_obj.name] = as_obj

    return as_map
