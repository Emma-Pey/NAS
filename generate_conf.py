#!/usr/bin/env python3

import json
import ipaddress
from dataclasses import dataclass, field
import os
import shutil
from typing import Dict, List, Optional


from typing import Dict, List, Optional
@dataclass
class Interface:
    name: str
    ipv6: ipaddress.IPv6Address
    prefix_len: int
    ospf_area: Optional[int] = None
    ripng: bool = False


@dataclass
class Neighbor:
    router: str
    type: str
    interface: str
    ospf_cost: Optional[int]=None 


@dataclass
class Router:
    name: str
    role: str
    asn: int
    neighbors: List[Neighbor]
    loopback: Optional[ipaddress.IPv6Address] = None
    interfaces: Dict[str, Interface] = field(default_factory=dict)
    bgp_neighbors: Dict[str, int] = field(default_factory=dict)
    bgp_policies: Dict[str, Dict[str, str]] = field(default_factory=dict)



@dataclass
class AutonomousSystem:
    name: str
    asn: int
    ipv6_prefix: ipaddress.IPv6Network
    loopback_pool: ipaddress.IPv6Network
    link_pool: ipaddress.IPv6Network
    inter_as_link_pool: ipaddress.IPv6Network
    protocol: str
    process_id: Optional[int] = None
    area: Optional[int] = None
    routers: Dict[str, Router] = field(default_factory=dict)

    def allocate_loopback(self) -> ipaddress.IPv6Address:
        used = {r.loopback for r in self.routers.values() if r.loopback}
        for ip in self.loopback_pool.hosts():
            if ip not in used:
                return ip
        raise ValueError("Loopback pool exhausted")

    def allocate_link_prefix(self, inter_as: bool = False) -> ipaddress.IPv6Network:
        pool = self.inter_as_link_pool if inter_as else self.link_pool
        subnets = list(pool.subnets(new_prefix=64))

        used = set()
        for r in self.routers.values():
            for iface in r.interfaces.values():
                net = ipaddress.IPv6Network(f"{iface.ipv6}/{iface.prefix_len}", strict=False)
                used.add(net.supernet(new_prefix=64))

        for net in subnets:
            if net not in used:
                return net

        raise ValueError("Link pool exhausted")



def parse_intent(path: str) -> Dict[str, AutonomousSystem]:
    data = json.load(open(path))
    as_map: Dict[str, AutonomousSystem] = {}

    for as_data in data["autonomous_systems"]:
        as_obj = AutonomousSystem(
            name=as_data["name"],
            asn=as_data["asn"],
            ipv6_prefix=ipaddress.IPv6Network(as_data["addressing"]["ipv6_prefix"]),
            loopback_pool=ipaddress.IPv6Network(as_data["addressing"]["loopback_pool"]),
            link_pool=ipaddress.IPv6Network(as_data["addressing"]["link_pool"]),
            inter_as_link_pool=ipaddress.IPv6Network(data["bgp"]["inter_as_link_pool"]),
            protocol=as_data["routing"]["protocol"],
            process_id=as_data["routing"].get("process_id"),
            area=as_data["routing"].get("area"),
        )
        for rdata in as_data["routers"]:
            router = Router(
                name=rdata["name"],
                role=rdata["role"],
                asn=as_obj.asn,
                neighbors=[Neighbor(**n) for n in rdata.get("neighbors", [])]
            )
            as_obj.routers[router.name] = router
        as_map[as_obj.name] = as_obj

    for as_name, policy_data in data.get("bgp_policies", {}).items():
        for entry in policy_data["neighbors"]:
            as_obj = as_map[as_name]
            router = as_obj.routers[entry["local_router"]]
            remote = entry["remote_router"]
            router.bgp_policies[remote] = entry
            print(router.bgp_policies[remote])

    return as_map


def allocate_addresses(as_map: Dict[str, AutonomousSystem]) -> None:
    # Loopback allocation
    for as_obj in as_map.values():
        for router in as_obj.routers.values():
            router.loopback = as_obj.allocate_loopback()

    # Intra-AS links allocation
    for as_obj in as_map.values():
        for router in as_obj.routers.values():
            for neigh in router.neighbors:
                if neigh.type == "intra-as":
                    neigh_router = as_obj.routers[neigh.router]
                    if neigh.interface not in router.interfaces:
                        link_prefix = as_obj.allocate_link_prefix(inter_as=False)
                        r_ip = link_prefix[1]
                        n_ip = link_prefix[2]

                        router.interfaces[neigh.interface] = Interface(
                            name=neigh.interface,
                            ipv6=r_ip,
                            prefix_len=64,
                            ospf_area=as_obj.area if as_obj.protocol == "ospfv3" else None,
                            ripng=(as_obj.protocol == "rip")
                        )

                        remote_iface = next(n.interface for n in neigh_router.neighbors if n.router == router.name)
                        neigh_router.interfaces[remote_iface] = Interface(
                            name=remote_iface,
                            ipv6=n_ip,
                            prefix_len=64,
                            ospf_area=as_obj.area if as_obj.protocol == "ospfv3" else None,
                            ripng=(as_obj.protocol == "rip")
                        )


def build_bgp_fullmesh(as_map: Dict[str, AutonomousSystem]) -> None:
    for as_obj in as_map.values():
        routers = list(as_obj.routers.values())
        for i in range(len(routers)):
            for j in range(i + 1, len(routers)):
                r1, r2 = routers[i], routers[j]
                r1.bgp_neighbors[str(r2.loopback)] = as_obj.asn
                r2.bgp_neighbors[str(r1.loopback)] = as_obj.asn



def build_inter_as_neighbors(as_map: Dict[str, AutonomousSystem]) -> None:
    for as_obj in as_map.values():
        for router in as_obj.routers.values():
            for neigh in router.neighbors:
                if neigh.type == "inter-as":
                    remote_as_name, remote_router_name = neigh.router.split(":")
                    if remote_router_name > router.name: ######################################################
                        remote_as = as_map[remote_as_name]
                        remote_router = remote_as.routers[remote_router_name]

                        link_prefix = as_obj.allocate_link_prefix(inter_as=True)
                        r_ip = link_prefix[1]
                        n_ip = link_prefix[2]

                        router.interfaces[neigh.interface] = Interface(
                            name=neigh.interface,
                            ipv6=r_ip,
                            prefix_len=64,
                            ospf_area=as_obj.area if as_obj.protocol == "ospfv3" else None,
                            ripng=False
                        )

                        remote_iface = next(n.interface for n in remote_router.neighbors if n.router == f"{as_obj.name}:{router.name}")
                        remote_router.interfaces[remote_iface] = Interface(
                            name=remote_iface,
                            ipv6=n_ip,
                            prefix_len=64,
                            ospf_area=remote_as.area if remote_as.protocol == "ospfv3" else None,
                            ripng=False
                        )

                        router.bgp_neighbors[str(n_ip)] = remote_as.asn
                        remote_router.bgp_neighbors[str(r_ip)] = as_obj.asn


"""def router_id_from_loopback(ip: ipaddress.IPv6Address) -> str:
    hextets = ip.exploded.split(":")
    last32 = int(hextets[-2], 16) << 16 | int(hextets[-1], 16)
    return f"{(last32 >> 24) & 0xFF}.{(last32 >> 16) & 0xFF}.{(last32 >> 8) & 0xFF}.{last32 & 0xFF}"
"""
def router_id_from_name(router_name: str) -> str:
    # R1 -> 1.1.1.1
    num = int(router_name.lstrip("R"))
    return f"{num}.{num}.{num}.{num}"


def generate_router_config(router: Router, as_obj: AutonomousSystem) -> str:
    rid = router_id_from_name(router.name)

    # Find inter-AS interface (if any)
    inter_as_iface = None
    for neigh in router.neighbors:
        if neigh.type == "inter-as":
            inter_as_iface = neigh.interface
            break

    lines = []
    lines.append("!")
    lines.append("version 15.2")
    lines.append("service timestamps debug datetime msec")
    lines.append("service timestamps log datetime msec")
    lines.append("!")
    lines.append(f"hostname {router.name}")
    lines.append("!")
    lines.append("boot-start-marker")
    lines.append("boot-end-marker")
    lines.append("!")
    lines.append("no aaa new-model")
    lines.append("no ip icmp rate-limit unreachable")
    lines.append("ip cef")
    lines.append("!")
    lines.append("no ip domain lookup")
    lines.append("ipv6 unicast-routing")
    lines.append("ipv6 cef")
    lines.append("!")
    lines.append("multilink bundle-name authenticated")
    lines.append("!")
    lines.append("ip tcp synwait-time 5")
    lines.append("!")
    lines.append("interface Loopback0")
    lines.append(" no ip address")
    lines.append(" no shutdown")
    lines.append(f" ipv6 address {router.loopback}/128")
    lines.append(" ipv6 enable")
    if as_obj.protocol == "ospfv3":
        lines.append(f" ipv6 ospf {as_obj.process_id} area {as_obj.area}")
    elif as_obj.protocol == "rip":
        lines.append(f" ipv6 rip {as_obj.name} enable")
    lines.append("!")

    for iface in router.interfaces.values():
        lines.append(f"interface {iface.name}")
        lines.append(" no ip address")
        lines.append(" no shutdown")
        lines.append(" negotiation auto")
        lines.append(f" ipv6 address {iface.ipv6}/{iface.prefix_len}")
        lines.append(" ipv6 enable")

        if as_obj.protocol == "ospfv3":
            lines.append(f" ipv6 ospf {as_obj.process_id} area {iface.ospf_area}")
            if hasattr(iface, "ospf_cost") and iface.ospf_cost is not None:
                lines.append(f" ipv6 ospf cost {iface.ospf_cost}")

        if iface.ripng:
            lines.append(f" ipv6 rip {as_obj.name} enable")

        lines.append("!")

    # BGP
    lines.append(f"router bgp {router.asn}")
    lines.append(f" bgp router-id {rid}")
    lines.append(" bgp log-neighbor-changes")
    if router.role == "border":
        lines.append(" no synchronization")
    lines.append(" no bgp default ipv4-unicast")

    for neigh_ip, neigh_asn in router.bgp_neighbors.items():
        lines.append(f" neighbor {neigh_ip} remote-as {neigh_asn}")
        if neigh_asn == router.asn:
            lines.append(f" neighbor {neigh_ip} update-source Loopback0")

    lines.append(" !")
    lines.append(" address-family ipv4")
    lines.append(" exit-address-family")
    lines.append(" !")
    lines.append(" address-family ipv6")

    if router.role == "border":
        lines.append(f"  network {as_obj.ipv6_prefix}")

    for neigh_ip, neigh_asn in router.bgp_neighbors.items():
        lines.append(f"  neighbor {neigh_ip} activate")
        if neigh_asn == router.asn:
            lines.append(f"  neighbor {neigh_ip} next-hop-self")

        # Match neighbor to remote_name
        remote_name = None
        for n in router.neighbors:
            if n.type == "inter-as":
                iface = router.interfaces.get(n.interface)
                if iface and str(iface.ipv6) == neigh_ip:
                    remote_name = n.router.split(":")[-1]
                    break

        if remote_name and remote_name in router.bgp_policies:
            policy = router.bgp_policies[remote_name]
            if "set_community" in policy:
                lines.append(f"  neighbor {neigh_ip} send-community")
                lines.append(f"  neighbor {neigh_ip} route-map SET-COMMUNITY-{remote_name} out")
            if "local_pref" in policy:
                lines.append(f"  neighbor {neigh_ip} route-map SET-LOCALPREF-{remote_name} in")
            if "export_only_community" in policy:
                lines.append(f"  neighbor {neigh_ip} route-map EXPORT-FILTER-{remote_name} out")

    lines.append(" exit-address-family")
    lines.append("!")

    # Route-maps and community-lists
    for remote_name, policy in router.bgp_policies.items():
        if "set_community" in policy:
            lines.append(f"route-map SET-COMMUNITY-{remote_name} permit 10")
            lines.append(f" set community {policy['set_community']}")
            lines.append("!")

        if "local_pref" in policy:
            lines.append(f"route-map SET-LOCALPREF-{remote_name} permit 10")
            lines.append(f" set local-preference {policy['local_pref']}")
            lines.append("!")

        if "export_only_community" in policy:
            comm = policy["export_only_community"]
            lines.append(f"ip community-list standard ONLY-EXPORT-{remote_name} permit {comm}")
            lines.append("!")
            lines.append(f"route-map EXPORT-FILTER-{remote_name} permit 10")
            lines.append(f" match community ONLY-EXPORT-{remote_name}")
            lines.append("!")
            lines.append(f"route-map EXPORT-FILTER-{remote_name} deny 20")
            lines.append("!")

    # static route for supernet (only on border routers)
    if router.role == "border":
        lines.append(f"ipv6 route {as_obj.ipv6_prefix} Null0")

    # IGP config
    if as_obj.protocol == "rip":
        lines.append(f"ipv6 router rip {as_obj.name}")
        lines.append("!")
    elif as_obj.protocol == "ospfv3":
        lines.append(f"ipv6 router ospf {as_obj.process_id}")
        lines.append(f" router-id {rid}")
        if router.role == "border" and inter_as_iface:
            lines.append(f" passive-interface {inter_as_iface}")
        lines.append("!")

    lines.append("control-plane")
    lines.append("!")
    lines.append("line con 0")
    lines.append(" exec-timeout 0 0")
    lines.append(" privilege level 15")
    lines.append(" logging synchronous")
    lines.append(" stopbits 1")
    lines.append("line aux 0")
    lines.append(" exec-timeout 0 0")
    lines.append(" privilege level 15")
    lines.append(" logging synchronous")
    lines.append(" stopbits 1")
    lines.append("line vty 0 4")
    lines.append(" login")
    lines.append("!")
    lines.append("!")
    lines.append("end")

    return "\n".join(lines)

def main(intent_path):
    as_map = parse_intent(intent_path)

    if os.path.exists("configs"):
        shutil.rmtree("configs") # Supprime le dossier s'il existe déjà
    os.makedirs("configs", exist_ok=True)


    allocate_addresses(as_map)
    build_bgp_fullmesh(as_map)
    build_inter_as_neighbors(as_map)

    for as_obj in as_map.values():
        for router in as_obj.routers.values():
            cfg = generate_router_config(router, as_obj)
            with open(f"configs/i{router.name[1:]}_startup-config.cfg", "w") as f:
                f.write(cfg)
            print(f"Generated i{router.name[1:]}_startup-config.cfg")


if __name__ == "__main__":
    intent_path = "int3AS.json"
    main(intent_path)
