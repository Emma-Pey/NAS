import math
import ipaddress
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Union


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
    vrf: Optional[str] = None
    ospf_cost: Optional[int] = None
    ingress_for: Optional[list] = None


@dataclass
class Router:
    name: str
    number: int
    role: str
    asn: int
    neighbors: List[Neighbor]
    loopback: Optional[Union[ipaddress.IPv4Address, ipaddress.IPv6Address]] = None
    interfaces: Dict[str, Interface] = field(default_factory=dict)
    bgp_neighbors: Dict[str, int] = field(default_factory=dict)
    bgp_policies: Dict[str, Dict[str, str]] = field(default_factory=dict)
    bgp_networks_v4: List[str] = field(default_factory=list)
    vrfs: Dict[str, Dict[str, Union[str, List[str]]]] = field(default_factory=dict)
    interface_vrf_map: Dict[str, str] = field(default_factory=dict)
    mpls_interfaces: List[str] = field(default_factory=list)
    bgp_vpnv4_neighbors: Dict[str, Dict[str, Union[int, bool, str]]] = field(default_factory=dict)
    vrf_bgp_neighbors: Dict[str, List[Dict[str, Union[int, str, bool]]]] = field(default_factory=dict)
    interface_options: Dict[str, Dict[str, Union[str, bool, int]]] = field(default_factory=dict)
    unused_interfaces: List[str] = field(default_factory=list)
    loopback_prefix_len_v4: int = 32
    route_reflector: bool = False
    rr_client_neighbors: Set[str] = field(default_factory=set)
    other_interfaces: Dict[str, str] = field(default_factory=dict)
    internet_gateway: bool = False


@dataclass
class AutonomousSystem:
    name: str
    asn: int
    ip_version: int
    loopback_pool: Union[ipaddress.IPv4Network, ipaddress.IPv6Network]
    link_pool: Union[ipaddress.IPv4Network, ipaddress.IPv6Network]
    inter_as_link_pool: Union[ipaddress.IPv4Network, ipaddress.IPv6Network, None]
    protocol: str
    ipv6_prefix: Optional[ipaddress.IPv6Network] = None
    process_id: Optional[int] = None
    area: Optional[int] = None
    ospf_style: str = "network"
    ios_legacy_defaults: bool = False
    mpls: bool = False
    rsvp: bool = False
    routers: Dict[str, Router] = field(default_factory=dict)
    allow_as_in: bool = False

    def allocate_loopback(self) -> Union[ipaddress.IPv4Address, ipaddress.IPv6Address]:
        used = {r.loopback for r in self.routers.values() if r.loopback}
        if not self.allow_as_in:
            for ip in self.loopback_pool.hosts():
                if ip not in used:
                    return ip
        else:
            num_routers = len(self.routers)
            if num_routers == 0:
                return next(self.loopback_pool.hosts())
            bits_needed = math.ceil(math.log2(num_routers))
            target_prefix = self.loopback_pool.prefixlen + bits_needed
            step = 2 ** ((32 if self.ip_version == 4 else 128) - target_prefix)
            first_ip = next(self.loopback_pool.hosts())
            next_ip = first_ip + (len(used) * step)
            if next_ip in self.loopback_pool:
                return next_ip
        raise ValueError("Loopback pool exhausted")

    def allocate_link_prefix(self, inter_as: bool = False):
        new_prefix = 30 if self.ip_version == 4 else 64
        pool = self.inter_as_link_pool if inter_as else self.link_pool
        subnets = list(pool.subnets(new_prefix=new_prefix))
        used = set()
        for r in self.routers.values():
            for iface in r.interfaces.values():
                if iface.prefix_len >= new_prefix:
                    net = ipaddress.ip_network(f"{iface.ip}/{iface.prefix_len}", strict=False)
                    used.add(net.supernet(new_prefix=new_prefix))
        for net in subnets:
            if net not in used:
                return net
        raise ValueError("Link pool exhausted")
