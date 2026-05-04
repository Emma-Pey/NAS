import math
import ipaddress
from typing import Dict, List

from models import Router, AutonomousSystem


def _mask(prefix_len: int) -> str:
    return str(ipaddress.IPv4Network(f"0.0.0.0/{prefix_len}").netmask)


def _wildcard(prefix_len: int) -> str:
    return str(ipaddress.IPv4Network(f"0.0.0.0/{prefix_len}").hostmask)


def router_id_from_name(router_name: str) -> str:
    num = int(router_name.lstrip("R"))
    return f"{num}.{num}.{num}.{num}"


def generate_router_config(router: Router, as_obj: AutonomousSystem) -> str:
    lines = []

    inter_as_iface = [n.interface for n in router.neighbors if n.type == "inter-as"]

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

    lines += ["!", "multilink bundle-name authenticated", "!"]

    if as_obj.ip_version == 4 and as_obj.ios_legacy_defaults:
        lines += ["no ipv6 cef", "!"]

    lines += ["ip tcp synwait-time 5", "!"]

    if as_obj.mpls and as_obj.rsvp:
        lines += ["mpls traffic-eng tunnels", "!"]

    # ------------------------------------------------------------------ IPv4
    if as_obj.ip_version == 4:
        rid = str(router.loopback)

        lines += ["interface Loopback0"]
        if router.role != "CE":
            lines += [f" ip address {router.loopback} {_mask(router.loopback_prefix_len_v4)}"]
        else:
            if not as_obj.allow_as_in:
                lines += [f" ip address {router.loopback} {as_obj.loopback_pool.netmask}"]
            else:
                bits_needed = math.ceil(math.log2(len(as_obj.routers))) if len(as_obj.routers) > 1 else 0
                current_prefix = as_obj.loopback_pool.prefixlen + bits_needed
                lines += [f" ip address {router.loopback} {_mask(current_prefix)}"]
        if as_obj.protocol == "ospf":
            lines.append(f" ip ospf {as_obj.process_id} area {as_obj.area}")
        lines += [" no shutdown", "!"]

        for iface in router.interfaces.values():
            iface_lines = [f"interface {iface.name}"]
            if iface.name in router.interface_vrf_map:
                iface_lines.append(f" ip vrf forwarding {router.interface_vrf_map[iface.name]}")
            iface_lines.append(f" ip address {iface.ip} {_mask(iface.prefix_len)}")
            if as_obj.protocol == "ospf" and iface.ospf_area is not None:
                iface_lines.append(f" ip ospf {as_obj.process_id} area {iface.ospf_area}")
            if iface.name in router.mpls_interfaces:
                iface_lines.append(" mpls ip")
                if as_obj.rsvp:
                    bw = 1000000 if "GigabitEthernet" in iface.name else 100000
                    iface_lines.append(" mpls traffic-eng tunnels")
                    iface_lines.append(f" ip rsvp bandwidth {bw}")
            options = router.interface_options.get(iface.name, {})
            if "duplex" in options:
                iface_lines.append(f" duplex {options['duplex']}")
            if options.get("negotiation_auto"):
                iface_lines.append(" negotiation auto")
            if options.get("shutdown", False):
                iface_lines += [" shutdown", "!"]
            else:
                iface_lines += [" no shutdown", "!"]
            lines += iface_lines

        for iface_name in router.unused_interfaces:
            if iface_name in router.interfaces:
                continue
            lines += [f"interface {iface_name}", " no ip address", " shutdown", " negotiation auto", "!"]

        if router.internet_gateway:
            lines += ["ip route 0.0.0.0 0.0.0.0 Null0", "!"]

        if router.vrfs:
            vrf_lines: List[str] = []
            for vrf_name, vrf in router.vrfs.items():
                vrf_lines += [f"ip vrf {vrf_name}", f" rd {vrf['rd']}"]
                for rt in vrf["rt_export"]:
                    vrf_lines.append(f" route-target export {rt}")
                for rt in vrf["rt_import"]:
                    vrf_lines.append(f" route-target import {rt}")
                vrf_lines.append("!")
            loopback_idx = lines.index("interface Loopback0")
            lines = lines[:loopback_idx] + vrf_lines + lines[loopback_idx:]

        if as_obj.protocol == "ospf":
            lines += [f"router ospf {as_obj.process_id}", f" router-id {rid}"]
            if as_obj.mpls and as_obj.rsvp:
                lines += [
                    " mpls traffic-eng router-id Loopback0",
                    f" mpls traffic-eng area {as_obj.area}",
                ]
            lines.append("!")

        if (
            router.bgp_neighbors
            or router.bgp_networks_v4
            or router.bgp_vpnv4_neighbors
            or router.vrf_bgp_neighbors
        ):
            lines += [f"router bgp {router.asn}", " bgp log-neighbor-changes"]

            vrf_bound_ips = {peer["ip"] for peers in router.vrf_bgp_neighbors.values() for peer in peers}

            for neigh_ip, neigh_asn in router.bgp_neighbors.items():
                if neigh_ip in vrf_bound_ips:
                    continue
                lines.append(f" neighbor {neigh_ip} remote-as {neigh_asn}")
                if neigh_asn == router.asn:
                    lines.append(f" neighbor {neigh_ip} update-source Loopback0")

            lines += [" !", " address-family ipv4"]

            neigh_ip_to_neighbor: Dict[str, object] = {}
            if router.role == "CE":
                bits_needed = math.ceil(math.log2(len(as_obj.routers))) if len(as_obj.routers) > 1 else 0
                current_prefix = as_obj.loopback_pool.prefixlen + bits_needed
                network_addr = ipaddress.IPv4Interface(f"{router.loopback}/{current_prefix}").network.network_address
                lines.append(f"  network {network_addr} mask {_mask(current_prefix)}")
                for iface_name in router.other_interfaces:
                    iface = router.interfaces.get(iface_name)
                    if iface:
                        net = ipaddress.IPv4Interface(f"{iface.ip}/{iface.prefix_len}").network
                        lines.append(f"  network {net.network_address} mask {_mask(iface.prefix_len)}")
                if router.internet_gateway:
                    lines.append("  network 0.0.0.0 mask 0.0.0.0")
                for neigh_ip in router.bgp_neighbors:
                    for n in router.neighbors:
                        local_iface = router.interfaces.get(n.interface)
                        if local_iface:
                            subnet = ipaddress.IPv4Network(
                                f"{local_iface.ip}/{local_iface.prefix_len}", strict=False
                            )
                            if ipaddress.IPv4Address(neigh_ip) in subnet:
                                neigh_ip_to_neighbor[neigh_ip] = n
                                break

            for neigh_ip, neigh_asn in router.bgp_neighbors.items():
                if neigh_ip in vrf_bound_ips:
                    continue
                lines.append(f"  neighbor {neigh_ip} activate")
                if neigh_ip in router.rr_client_neighbors:
                    lines.append(f"  neighbor {neigh_ip} route-reflector-client")
                if neigh_asn == router.asn:
                    lines.append(f"  neighbor {neigh_ip} next-hop-self")
                if as_obj.allow_as_in:
                    lines.append(f"  neighbor {neigh_ip} allowas-in")
                n = neigh_ip_to_neighbor.get(neigh_ip)
                if n and n.ingress_for:
                    remote_name = n.router.split(":")[-1]
                    lines.append(f"  neighbor {neigh_ip} send-community")
                    lines.append(f"  neighbor {neigh_ip} route-map TO_{remote_name} out")
            lines += [" exit-address-family"]

            if router.bgp_vpnv4_neighbors:
                lines += [" !", " address-family vpnv4"]
                if router.route_reflector:
                    lines.append("  no bgp default route-target filter")
                for neigh_ip, opts in router.bgp_vpnv4_neighbors.items():
                    if opts.get("activate", True):
                        lines.append(f"  neighbor {neigh_ip} activate")
                    else:
                        lines.append(f"  no neighbor {neigh_ip} activate")
                    if opts.get("send_community_extended"):
                        lines.append(f"  neighbor {neigh_ip} send-community extended")
                    if neigh_ip in router.rr_client_neighbors:
                        lines.append(f"  neighbor {neigh_ip} route-reflector-client")
                lines.append(" exit-address-family")

            for vrf_name, peers in router.vrf_bgp_neighbors.items():
                lines += [" !", f" address-family ipv4 vrf {vrf_name}"]
                for peer in peers:
                    peer_ip = peer["ip"]
                    lines.append(f"  neighbor {peer_ip} remote-as {peer['asn']}")
                    if peer.get("activate", True):
                        lines.append(f"  neighbor {peer_ip} activate")
                    if peer.get("allowas_in"):
                        lines.append(f"  neighbor {peer_ip} allowas-in")
                    if router.role == "PE" and peer.get("apply_ingress_policy"):
                        lines.append(f"  neighbor {peer_ip} route-map CLIENT_IN in")
                lines.append(" exit-address-family")

            lines.append("!")

            if router.role == "PE":
                if as_obj.ios_legacy_defaults:
                    lines += ["ip forward-protocol nd", "!"]
                lines += ["ip community-list standard CL_PRIMARY permit 65636", "!"]
                if as_obj.ios_legacy_defaults:
                    lines += ["no ip http server", "no ip http secure-server", "!"]
                lines += [
                    "route-map CLIENT_IN permit 10",
                    " match community CL_PRIMARY",
                    " set local-preference 200",
                    "!",
                    "route-map CLIENT_IN permit 20",
                    " set local-preference 100",
                    "!",
                ]
                return "\n".join(lines + [
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
                ])

            if router.role == "CE":
                ingress_neighbors = [n for n in router.neighbors if n.type == "inter-as" and n.ingress_for]
                if ingress_neighbors:
                    all_ifaces = {"Loopback0": router.loopback_prefix_len_v4}
                    for iface_name in router.other_interfaces:
                        iface = router.interfaces.get(iface_name)
                        if iface:
                            all_ifaces[iface_name] = iface.prefix_len

                    for iface_name in all_ifaces:
                        if iface_name == "Loopback0":
                            bits_needed = math.ceil(math.log2(len(as_obj.routers))) if len(as_obj.routers) > 1 else 0
                            lo_prefix = as_obj.loopback_pool.prefixlen + bits_needed
                            net = ipaddress.IPv4Interface(f"{router.loopback}/{lo_prefix}").network
                            plen = lo_prefix
                        else:
                            iface = router.interfaces.get(iface_name)
                            net = ipaddress.IPv4Interface(f"{iface.ip}/{iface.prefix_len}").network
                            plen = iface.prefix_len
                        pl_name = f"PL_{iface_name.replace('Loopback', 'L').replace('/', '_')}"
                        lines += [f"ip prefix-list {pl_name} seq 5 permit {net.network_address}/{plen}", "!"]

                    for neigh in ingress_neighbors:
                        remote_name = neigh.router.split(":")[-1]
                        rm_name = f"TO_{remote_name}"
                        lines += [f"route-map {rm_name} permit 10"]
                        for iface in neigh.ingress_for:
                            pl = f"PL_{iface.replace('Loopback', 'L').replace('/', '_')}"
                            lines += [f" match ip address prefix-list {pl}"]
                        lines += [" set community 65636", "!"]
                        lines += [f"route-map {rm_name} permit 20", "!"]

    # ------------------------------------------------------------------ IPv6
    else:
        rid = router_id_from_name(router.name)

        inter_as_iface_v6 = next(
            (n.interface for n in router.neighbors if n.type == "inter-as"), None
        )

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

        for remote_name, policy in router.bgp_policies.items():
            if "set_community" in policy:
                lines += [
                    f"route-map SET-COMMUNITY-{remote_name} permit 10",
                    f" set community {policy['set_community']}",
                    "!",
                ]
            if "local_pref" in policy:
                lines += [
                    f"route-map SET-LOCALPREF-{remote_name} permit 10",
                    f" set local-preference {policy['local_pref']}",
                    "!",
                ]
            if "export_only_community" in policy:
                comm = policy["export_only_community"]
                lines += [
                    f"ip community-list standard ONLY-EXPORT-{remote_name} permit {comm}", "!",
                    f"route-map EXPORT-FILTER-{remote_name} permit 10",
                    f" match community ONLY-EXPORT-{remote_name}", "!",
                    f"route-map EXPORT-FILTER-{remote_name} deny 20", "!",
                ]

        if router.role == "border":
            lines.append(f"ipv6 route {as_obj.ipv6_prefix} Null0")

        if as_obj.protocol == "rip":
            lines += [f"ipv6 router rip {as_obj.name}", "!"]
        elif as_obj.protocol == "ospfv3":
            lines += [f"ipv6 router ospf {as_obj.process_id}", f" router-id {rid}"]
            if router.role == "border" and inter_as_iface_v6:
                lines.append(f" passive-interface {inter_as_iface_v6}")
            lines.append("!")

    # ------------------------------------------------------------------ Common
    if as_obj.ip_version == 4 and as_obj.ios_legacy_defaults:
        lines += ["ip forward-protocol nd", "!", "no ip http server", "no ip http secure-server", "!"]

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
