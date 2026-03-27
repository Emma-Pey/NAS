#!/usr/bin/env python3

import json
import ipaddress
import sys
from dataclasses import dataclass, field
import os
import shutil
from typing import Dict, List, Optional, Union


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Interface:
    name: str
    ip: Union[ipaddress.IPv4Address, ipaddress.IPv6Address]
    prefix_len: int
    ospf_area: Optional[int] = None
    ripng: bool = False
    ospf_cost: Optional[int] = None


@dataclass
class Neighbor:
    router: str
    type: str
    interface: str
    ospf_cost: Optional[int] = None


@dataclass
class Router:
    name: str
    role: str
    asn: int
    neighbors: List[Neighbor]
    loopback: Optional[Union[ipaddress.IPv4Address, ipaddress.IPv6Address]] = None
    interfaces: Dict[str, Interface] = field(default_factory=dict)
    bgp_neighbors: Dict[str, int] = field(default_factory=dict)
    bgp_policies: Dict[str, Dict[str, str]] = field(default_factory=dict)
    bgp_neighbor_options: Dict[str, Dict[str, Union[str, int, bool]]] = field(default_factory=dict)
    bgp_networks_v4: List[str] = field(default_factory=list)


@dataclass
class AutonomousSystem:
    name: str
    asn: int
    ip_version: int                                    # 4 or 6
    loopback_pool: Union[ipaddress.IPv4Network, ipaddress.IPv6Network]
    link_pool: Union[ipaddress.IPv4Network, ipaddress.IPv6Network]
    inter_as_link_pool: Union[ipaddress.IPv4Network, ipaddress.IPv6Network, None]
    protocol: str
    ipv6_prefix: Optional[ipaddress.IPv6Network] = None
    process_id: Optional[int] = None
    area: Optional[int] = None
    ospf_style: str = "network"
    routers: Dict[str, Router] = field(default_factory=dict)

    def allocate_loopback(self) -> Union[ipaddress.IPv4Address, ipaddress.IPv6Address]:
        used = {r.loopback for r in self.routers.values() if r.loopback}
        for ip in self.loopback_pool.hosts():
            if ip not in used:
                return ip
        raise ValueError("Loopback pool exhausted")

    def allocate_link_prefix(self, inter_as: bool = False):
        new_prefix = 30 if self.ip_version == 4 else 64
        pool = (self.inter_as_link_pool if inter_as else self.link_pool)
        subnets = list(pool.subnets(new_prefix=new_prefix))

        used = set()
        for r in self.routers.values():
            for iface in r.interfaces.values():
                net = ipaddress.ip_network(f"{iface.ip}/{iface.prefix_len}", strict=False)
                used.add(net.supernet(new_prefix=new_prefix))

        for net in subnets:
            if net not in used:
                return net

        raise ValueError("Link pool exhausted")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_intent(path: str) -> Dict[str, AutonomousSystem]:
    data = json.load(open(path))
    as_map: Dict[str, AutonomousSystem] = {}

    for as_data in data["autonomous_systems"]:
        addr = as_data["addressing"]

        # Detect IP version from addressing keys
        if "ipv6_prefix" in addr:
            ip_version = 6
            ipv6_prefix = ipaddress.IPv6Network(addr["ipv6_prefix"])
            loopback_pool = ipaddress.IPv6Network(addr["loopback_pool"])
            link_pool = ipaddress.IPv6Network(addr["link_pool"])
            inter_as_pool = ipaddress.IPv6Network(data["bgp"]["inter_as_link_pool"]) \
                if "bgp" in data else None
        else:
            ip_version = 4
            ipv6_prefix = None
            loopback_pool = ipaddress.IPv4Network(addr["loopback_pool"])
            link_pool = ipaddress.IPv4Network(addr["link_pool"])
            inter_as_pool = None

        as_obj = AutonomousSystem(
            name=as_data["name"],
            asn=as_data["asn"],
            ip_version=ip_version,
            ipv6_prefix=ipv6_prefix,
            loopback_pool=loopback_pool,
            link_pool=link_pool,
            inter_as_link_pool=inter_as_pool,
            protocol=as_data["routing"]["protocol"],
            process_id=as_data["routing"].get("process_id"),
            area=as_data["routing"].get("area"),
            ospf_style=as_data["routing"].get("ospf_style", "network"),
        )
        for rdata in as_data["routers"]:
            router = Router(
                name=rdata["name"],
                role=rdata["role"],
                asn=as_obj.asn,
                neighbors=[Neighbor(**n) for n in rdata.get("neighbors", [])]
            )

            # Optional explicit IPv4 BGP settings (used by MPLS VPN / CE-PE scenarios)
            router.bgp_networks_v4 = rdata.get("bgp_networks_v4", [])
            for b in rdata.get("bgp_neighbors", []):
                neigh_ip = b["ip"]
                router.bgp_neighbors[neigh_ip] = b["asn"]
                options: Dict[str, Union[str, int, bool]] = {}
                for key in ("update_source", "allowas_in", "activate", "next_hop_self"):
                    if key in b:
                        options[key] = b[key]
                router.bgp_neighbor_options[neigh_ip] = options

            as_obj.routers[router.name] = router
        as_map[as_obj.name] = as_obj

    for as_name, policy_data in data.get("bgp_policies", {}).items():
        for entry in policy_data["neighbors"]:
            as_obj = as_map[as_name]
            router = as_obj.routers[entry["local_router"]]
            remote = entry["remote_router"]
            router.bgp_policies[remote] = entry

    return as_map


# ---------------------------------------------------------------------------
# Address allocation
# ---------------------------------------------------------------------------

def allocate_addresses(as_map: Dict[str, AutonomousSystem]) -> None:
    # Loopbacks
    for as_obj in as_map.values():
        for router in as_obj.routers.values():
            router.loopback = as_obj.allocate_loopback()

    # Intra-AS links
    for as_obj in as_map.values():
        for router in as_obj.routers.values():
            for neigh in router.neighbors:
                if neigh.type == "intra-as":
                    neigh_router = as_obj.routers[neigh.router]
                    if neigh.interface not in router.interfaces:
                        link_prefix = as_obj.allocate_link_prefix(inter_as=False)
                        r_ip = link_prefix[1]
                        n_ip = link_prefix[2]
                        plen = 30 if as_obj.ip_version == 4 else 64

                        router.interfaces[neigh.interface] = Interface(
                            name=neigh.interface,
                            ip=r_ip,
                            prefix_len=plen,
                            ospf_area=as_obj.area if as_obj.protocol in ("ospfv3", "ospf") else None,
                            ripng=(as_obj.protocol == "rip"),
                            ospf_cost=neigh.ospf_cost,
                        )

                        remote_iface = next(n.interface for n in neigh_router.neighbors if n.router == router.name)
                        remote_neigh = next(n for n in neigh_router.neighbors if n.router == router.name)
                        neigh_router.interfaces[remote_iface] = Interface(
                            name=remote_iface,
                            ip=n_ip,
                            prefix_len=plen,
                            ospf_area=as_obj.area if as_obj.protocol in ("ospfv3", "ospf") else None,
                            ripng=(as_obj.protocol == "rip"),
                            ospf_cost=remote_neigh.ospf_cost,
                        )


def build_bgp_fullmesh(as_map: Dict[str, AutonomousSystem]) -> None:
    for as_obj in as_map.values():
        if as_obj.ip_version == 4:
            continue  # No BGP in basic IPv4 setup
        routers = list(as_obj.routers.values())
        for i in range(len(routers)):
            for j in range(i + 1, len(routers)):
                r1, r2 = routers[i], routers[j]
                r1.bgp_neighbors[str(r2.loopback)] = as_obj.asn
                r2.bgp_neighbors[str(r1.loopback)] = as_obj.asn


def build_inter_as_neighbors(as_map: Dict[str, AutonomousSystem]) -> None:
    for as_obj in as_map.values():
        if as_obj.ip_version == 4:
            continue  # No inter-AS in basic IPv4 setup
        for router in as_obj.routers.values():
            for neigh in router.neighbors:
                if neigh.type == "inter-as":
                    remote_as_name, remote_router_name = neigh.router.split(":")
                    if remote_router_name > router.name:
                        remote_as = as_map[remote_as_name]
                        remote_router = remote_as.routers[remote_router_name]

                        link_prefix = as_obj.allocate_link_prefix(inter_as=True)
                        r_ip = link_prefix[1]
                        n_ip = link_prefix[2]

                        router.interfaces[neigh.interface] = Interface(
                            name=neigh.interface,
                            ip=r_ip,
                            prefix_len=64,
                            ospf_area=as_obj.area if as_obj.protocol == "ospfv3" else None,
                            ripng=False,
                        )

                        remote_iface = next(n.interface for n in remote_router.neighbors if n.router == f"{as_obj.name}:{router.name}")
                        remote_router.interfaces[remote_iface] = Interface(
                            name=remote_iface,
                            ip=n_ip,
                            prefix_len=64,
                            ospf_area=remote_as.area if remote_as.protocol == "ospfv3" else None,
                            ripng=False,
                        )

                        router.bgp_neighbors[str(n_ip)] = remote_as.asn
                        remote_router.bgp_neighbors[str(r_ip)] = as_obj.asn


# ---------------------------------------------------------------------------
# Config generation
# ---------------------------------------------------------------------------

def router_id_from_name(router_name: str) -> str:
    """R1 → 1.1.1.1  (IPv6 mode only, where names follow R<N> convention)"""
    num = int(router_name.lstrip("R"))
    return f"{num}.{num}.{num}.{num}"


def _mask(prefix_len: int) -> str:
    return str(ipaddress.IPv4Network(f"0.0.0.0/{prefix_len}").netmask)

def _wildcard(prefix_len: int) -> str:
    return str(ipaddress.IPv4Network(f"0.0.0.0/{prefix_len}").hostmask)


def generate_router_config(router: Router, as_obj: AutonomousSystem) -> str:
    lines = []

    lines += [
        "!",
        "version 15.2",
        "service timestamps debug datetime msec",
        "service timestamps log datetime msec",
        "!",
        f"hostname {router.name}",
        "!",
        "boot-start-marker",
        "boot-end-marker",
        "!",
        "no aaa new-model",
        "no ip icmp rate-limit unreachable",
        "ip cef",
        "!",
        "no ip domain lookup",
    ]

    if as_obj.ip_version == 6:
        lines += ["ipv6 unicast-routing", "ipv6 cef"]

    lines += [
        "!",
        "multilink bundle-name authenticated",
        "!",
        "ip tcp synwait-time 5",
        "!",
    ]

    # ------------------------------------------------------------------ IPv4
    if as_obj.ip_version == 4:
        rid = str(router.loopback)

        # Loopback
        lines += [
            "interface Loopback0",
            f" ip address {router.loopback} 255.255.255.255",
        ]
        if as_obj.protocol == "ospf" and as_obj.ospf_style == "interface":
            lines.append(f" ip ospf {as_obj.process_id} area {as_obj.area}")
        lines += [
            " no shutdown",
            "!",
        ]

        # Physical interfaces
        for iface in router.interfaces.values():
            iface_lines = [
                f"interface {iface.name}",
                f" ip address {iface.ip} {_mask(iface.prefix_len)}",
            ]
            if as_obj.protocol == "ospf" and as_obj.ospf_style == "interface":
                iface_lines.append(f" ip ospf {as_obj.process_id} area {iface.ospf_area}")
            iface_lines += [" no shutdown", "!"]
            lines += iface_lines

        # OSPFv2
        if as_obj.protocol == "ospf":
            lines += [
                f"router ospf {as_obj.process_id}",
                f" router-id {rid}",
            ]
            if as_obj.ospf_style == "network":
                lines.append(f" network {router.loopback} 0.0.0.0 area {as_obj.area}")
                for iface in router.interfaces.values():
                    net = ipaddress.IPv4Interface(f"{iface.ip}/{iface.prefix_len}").network
                    lines.append(f" network {net.network_address} {_wildcard(iface.prefix_len)} area {iface.ospf_area}")
            lines.append("!")

        # Optional IPv4 BGP block (manual-like CE/PE configs)
        if router.bgp_neighbors or router.bgp_networks_v4:
            lines += [
                f"router bgp {router.asn}",
                " bgp log-neighbor-changes",
            ]
            for neigh_ip, neigh_asn in router.bgp_neighbors.items():
                lines.append(f" neighbor {neigh_ip} remote-as {neigh_asn}")
                options = router.bgp_neighbor_options.get(neigh_ip, {})
                update_source = options.get("update_source")
                if update_source:
                    lines.append(f" neighbor {neigh_ip} update-source {update_source}")
                if "allowas_in" in options:
                    allowas_value = options["allowas_in"]
                    if isinstance(allowas_value, bool):
                        if allowas_value:
                            lines.append(f" neighbor {neigh_ip} allowas-in")
                    else:
                        lines.append(f" neighbor {neigh_ip} allowas-in {allowas_value}")

            lines += [" !", " address-family ipv4"]
            for network in router.bgp_networks_v4:
                lines.append(f"  network {network}")
            for neigh_ip in router.bgp_neighbors.keys():
                options = router.bgp_neighbor_options.get(neigh_ip, {})
                if options.get("activate", True):
                    lines.append(f"  neighbor {neigh_ip} activate")
                else:
                    lines.append(f"  no neighbor {neigh_ip} activate")
                if options.get("next_hop_self"):
                    lines.append(f"  neighbor {neigh_ip} next-hop-self")
            lines += [" exit-address-family", "!"]

    # ------------------------------------------------------------------ IPv6
    else:
        rid = router_id_from_name(router.name)

        inter_as_iface = next(
            (n.interface for n in router.neighbors if n.type == "inter-as"), None
        )

        # Loopback
        lines += [
            "interface Loopback0",
            " no ip address",
            " no shutdown",
            f" ipv6 address {router.loopback}/128",
            " ipv6 enable",
        ]
        if as_obj.protocol == "ospfv3":
            lines.append(f" ipv6 ospf {as_obj.process_id} area {as_obj.area}")
        elif as_obj.protocol == "rip":
            lines.append(f" ipv6 rip {as_obj.name} enable")
        lines.append("!")

        # Physical interfaces
        for iface in router.interfaces.values():
            lines += [
                f"interface {iface.name}",
                " no ip address",
                " no shutdown",
                " negotiation auto",
                f" ipv6 address {iface.ip}/{iface.prefix_len}",
                " ipv6 enable",
            ]
            if as_obj.protocol == "ospfv3":
                lines.append(f" ipv6 ospf {as_obj.process_id} area {iface.ospf_area}")
                if iface.ospf_cost is not None:
                    lines.append(f" ipv6 ospf cost {iface.ospf_cost}")
            if iface.ripng:
                lines.append(f" ipv6 rip {as_obj.name} enable")
            lines.append("!")

        # BGP
        lines += [
            f"router bgp {router.asn}",
            f" bgp router-id {rid}",
            " bgp log-neighbor-changes",
        ]
        if router.role == "border":
            lines.append(" no synchronization")
        lines.append(" no bgp default ipv4-unicast")

        for neigh_ip, neigh_asn in router.bgp_neighbors.items():
            lines.append(f" neighbor {neigh_ip} remote-as {neigh_asn}")
            if neigh_asn == router.asn:
                lines.append(f" neighbor {neigh_ip} update-source Loopback0")

        lines += [" !", " address-family ipv4", " exit-address-family", " !", " address-family ipv6"]

        if router.role == "border":
            lines.append(f"  network {as_obj.ipv6_prefix}")

        for neigh_ip, neigh_asn in router.bgp_neighbors.items():
            lines.append(f"  neighbor {neigh_ip} activate")
            if neigh_asn == router.asn:
                lines.append(f"  neighbor {neigh_ip} next-hop-self")

            remote_name = None
            for n in router.neighbors:
                if n.type == "inter-as":
                    iface = router.interfaces.get(n.interface)
                    if iface and str(iface.ip) == neigh_ip:
                        remote_name = n.router.split(":")[-1]
                        break

            if remote_name and remote_name in router.bgp_policies:
                policy = router.bgp_policies[remote_name]
                if "set_community" in policy:
                    lines += [
                        f"  neighbor {neigh_ip} send-community",
                        f"  neighbor {neigh_ip} route-map SET-COMMUNITY-{remote_name} out",
                    ]
                if "local_pref" in policy:
                    lines.append(f"  neighbor {neigh_ip} route-map SET-LOCALPREF-{remote_name} in")
                if "export_only_community" in policy:
                    lines.append(f"  neighbor {neigh_ip} route-map EXPORT-FILTER-{remote_name} out")

        lines += [" exit-address-family", "!"]

        # Route-maps
        for remote_name, policy in router.bgp_policies.items():
            if "set_community" in policy:
                lines += [f"route-map SET-COMMUNITY-{remote_name} permit 10", f" set community {policy['set_community']}", "!"]
            if "local_pref" in policy:
                lines += [f"route-map SET-LOCALPREF-{remote_name} permit 10", f" set local-preference {policy['local_pref']}", "!"]
            if "export_only_community" in policy:
                comm = policy["export_only_community"]
                lines += [
                    f"ip community-list standard ONLY-EXPORT-{remote_name} permit {comm}", "!",
                    f"route-map EXPORT-FILTER-{remote_name} permit 10", f" match community ONLY-EXPORT-{remote_name}", "!",
                    f"route-map EXPORT-FILTER-{remote_name} deny 20", "!",
                ]

        if router.role == "border":
            lines.append(f"ipv6 route {as_obj.ipv6_prefix} Null0")

        # IGP
        if as_obj.protocol == "rip":
            lines += [f"ipv6 router rip {as_obj.name}", "!"]
        elif as_obj.protocol == "ospfv3":
            lines += [f"ipv6 router ospf {as_obj.process_id}", f" router-id {rid}"]
            if router.role == "border" and inter_as_iface:
                lines.append(f" passive-interface {inter_as_iface}")
            lines.append("!")

    # ------------------------------------------------------------------ Common
    lines += [
        "control-plane",
        "!",
        "line con 0",
        " exec-timeout 0 0",
        " privilege level 15",
        " logging synchronous",
        " stopbits 1",
        "line aux 0",
        " exec-timeout 0 0",
        " privilege level 15",
        " logging synchronous",
        " stopbits 1",
        "line vty 0 4",
        " login",
        "!",
        "end",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(intent_path: str) -> None:
    as_map = parse_intent(intent_path)

    if os.path.exists("configs"):
        shutil.rmtree("configs")
    os.makedirs("configs", exist_ok=True)

    allocate_addresses(as_map)
    build_bgp_fullmesh(as_map)
    build_inter_as_neighbors(as_map)

    for as_obj in as_map.values():
        for router in as_obj.routers.values():
            cfg = generate_router_config(router, as_obj)
            fname = f"configs/{router.name}_startup-config.cfg"
            with open(fname, "w") as f:
                f.write(cfg)
            print(f"Generated {fname}")

    # Address summary
    print("\n=== Address Summary ===")
    for as_obj in as_map.values():
        print(f"\n{as_obj.name} (IPv{as_obj.ip_version}, {as_obj.protocol}):")
        for router in as_obj.routers.values():
            lo_len = 32 if as_obj.ip_version == 4 else 128
            print(f"  {router.name:<6}  Lo0: {router.loopback}/{lo_len}")
            for iface in router.interfaces.values():
                print(f"         {iface.name}: {iface.ip}/{iface.prefix_len}")


if __name__ == "__main__":
    intent_path = sys.argv[1] if len(sys.argv) > 1 else "intent_basic.json"
    main(intent_path)
