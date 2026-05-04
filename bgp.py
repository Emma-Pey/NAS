from typing import Dict

from models import AutonomousSystem, Interface


def build_bgp_fullmesh(as_map: Dict[str, AutonomousSystem]) -> None:
    for as_obj in as_map.values():
        if not as_obj.mpls:
            continue

        rr_routers = [r for r in as_obj.routers.values() if r.route_reflector]
        if rr_routers:
            pe_routers = [r for r in as_obj.routers.values() if r.role.lower() == "pe"]
            for client in pe_routers:
                if client.route_reflector:
                    continue
                for rr in rr_routers:
                    client.bgp_neighbors[str(rr.loopback)] = as_obj.asn
                    rr.bgp_neighbors[str(client.loopback)] = as_obj.asn
                    rr.rr_client_neighbors.add(str(client.loopback))
            for i in range(len(rr_routers)):
                for j in range(i + 1, len(rr_routers)):
                    rr1, rr2 = rr_routers[i], rr_routers[j]
                    rr1.bgp_neighbors[str(rr2.loopback)] = as_obj.asn
                    rr2.bgp_neighbors[str(rr1.loopback)] = as_obj.asn
            continue

        routers = list(as_obj.routers.values())
        for i in range(len(routers)):
            for j in range(i + 1, len(routers)):
                r1, r2 = routers[i], routers[j]
                r1.bgp_neighbors[str(r2.loopback)] = as_obj.asn
                r2.bgp_neighbors[str(r1.loopback)] = as_obj.asn


def build_vpnv4_fullmesh(as_map: Dict[str, AutonomousSystem]) -> None:
    for as_obj in as_map.values():
        if not as_obj.mpls:
            continue

        rr_routers = [r for r in as_obj.routers.values() if r.route_reflector]
        if rr_routers:
            pe_routers = [r for r in as_obj.routers.values() if r.role.lower() == "pe"]
            for client in pe_routers:
                if client.route_reflector:
                    continue
                for rr in rr_routers:
                    client.bgp_vpnv4_neighbors[str(rr.loopback)] = {
                        "asn": as_obj.asn, "activate": True, "send_community_extended": True,
                    }
                    rr.bgp_vpnv4_neighbors[str(client.loopback)] = {
                        "asn": as_obj.asn, "activate": True, "send_community_extended": True,
                    }
            for i in range(len(rr_routers)):
                for j in range(i + 1, len(rr_routers)):
                    rr1, rr2 = rr_routers[i], rr_routers[j]
                    rr1.bgp_vpnv4_neighbors[str(rr2.loopback)] = {
                        "asn": as_obj.asn, "activate": True, "send_community_extended": True,
                    }
                    rr2.bgp_vpnv4_neighbors[str(rr1.loopback)] = {
                        "asn": as_obj.asn, "activate": True, "send_community_extended": True,
                    }
            continue

        pe_routers = [r for r in as_obj.routers.values() if r.role.lower() == "pe"]
        for r1 in pe_routers:
            for r2 in pe_routers:
                if r1 is r2:
                    continue
                peer_ip = str(r2.loopback)
                if peer_ip not in r1.bgp_vpnv4_neighbors:
                    r1.bgp_vpnv4_neighbors[peer_ip] = {
                        "asn": as_obj.asn, "activate": True, "send_community_extended": True,
                    }


def build_inter_as_neighbors(as_map: Dict[str, AutonomousSystem]) -> None:
    for as_obj in as_map.values():
        for router in as_obj.routers.values():
            for neigh in router.neighbors:
                if neigh.type != "inter-as":
                    continue

                remote_parts = neigh.router.split(":")
                if len(remote_parts) < 2:
                    continue
                remote_as_name, remote_router_name = remote_parts

                if remote_router_name <= router.name:
                    continue
                if remote_as_name not in as_map:
                    continue

                remote_as = as_map[remote_as_name]
                remote_router = remote_as.routers[remote_router_name]

                link_prefix = as_obj.allocate_link_prefix(inter_as=False)
                r_ip = link_prefix[1]
                n_ip = link_prefix[2]
                p_len = 30 if as_obj.ip_version == 4 else 64

                router.interfaces[neigh.interface] = Interface(
                    name=neigh.interface, ip=r_ip, prefix_len=p_len,
                )

                try:
                    remote_iface_name = next(
                        n.interface for n in remote_router.neighbors
                        if n.router == f"{as_obj.name}:{router.name}"
                    )
                    remote_router.interfaces[remote_iface_name] = Interface(
                        name=remote_iface_name, ip=n_ip, prefix_len=p_len,
                    )
                except StopIteration:
                    print(f"Erreur : Pas de lien retour trouvé sur {remote_router_name} vers {router.name}")
                    continue

                vrf_name = router.interface_vrf_map.get(neigh.interface)
                if vrf_name:
                    router.vrf_bgp_neighbors.setdefault(vrf_name, []).append({
                        "ip": str(n_ip), "asn": remote_as.asn,
                        "activate": True, "apply_ingress_policy": True,
                    })
                    router.bgp_neighbors[str(n_ip)] = remote_as.asn
                else:
                    router.bgp_neighbors[str(n_ip)] = remote_as.asn

                remote_vrf = remote_router.interface_vrf_map.get(remote_iface_name)
                if remote_vrf:
                    remote_router.vrf_bgp_neighbors.setdefault(remote_vrf, []).append({
                        "ip": str(r_ip), "asn": as_obj.asn,
                        "activate": True, "apply_ingress_policy": True,
                    })
                    remote_router.bgp_neighbors[str(r_ip)] = as_obj.asn
                else:
                    remote_router.bgp_neighbors[str(r_ip)] = as_obj.asn
