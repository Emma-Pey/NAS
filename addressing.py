import ipaddress
from typing import Dict

from models import AutonomousSystem, Interface


def allocate_addresses(as_map: Dict[str, AutonomousSystem]) -> None:
    for as_obj in as_map.values():
        for router in as_obj.routers.values():
            if router.loopback is None:
                router.loopback = as_obj.allocate_loopback()
                for vrf_data in router.vrfs.values():
                    vrf_data["rd"] = (
                        f"{as_obj.asn}:"
                        f"{int(vrf_data['rd'].split(':')[1]) + int(str(router.loopback).split('.')[-1])}"
                    )

    for as_obj in as_map.values():
        for router in as_obj.routers.values():
            for iface_name, cidr in router.other_interfaces.items():
                net = ipaddress.IPv4Network(cidr, strict=False)
                router.interfaces[iface_name] = Interface(
                    name=iface_name,
                    ip=next(net.hosts()),
                    prefix_len=net.prefixlen,
                )

            for neigh in router.neighbors:
                if neigh.type != "intra-as":
                    continue
                neigh_router = as_obj.routers[neigh.router]
                if as_obj.mpls and neigh.interface not in router.mpls_interfaces:
                    router.mpls_interfaces.append(neigh.interface)
                if neigh.interface in router.interfaces:
                    continue

                link_prefix = as_obj.allocate_link_prefix(inter_as=False)
                r_ip = link_prefix[1]
                n_ip = link_prefix[2]
                plen = 30 if as_obj.ip_version == 4 else 64
                ospf_area = as_obj.area if as_obj.protocol in ("ospfv3", "ospf") else None
                is_rip = as_obj.protocol == "rip"

                router.interfaces[neigh.interface] = Interface(
                    name=neigh.interface,
                    ip=r_ip,
                    prefix_len=plen,
                    ospf_area=ospf_area,
                    ripng=is_rip,
                    ospf_cost=neigh.ospf_cost,
                )
                remote_iface = next(n.interface for n in neigh_router.neighbors if n.router == router.name)
                remote_neigh = next(n for n in neigh_router.neighbors if n.router == router.name)
                neigh_router.interfaces[remote_iface] = Interface(
                    name=remote_iface,
                    ip=n_ip,
                    prefix_len=plen,
                    ospf_area=ospf_area,
                    ripng=is_rip,
                    ospf_cost=remote_neigh.ospf_cost,
                )
