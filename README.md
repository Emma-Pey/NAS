# NAS — Network Automation Scripts

Génère automatiquement les configs de démarrage Cisco IOS pour des topologies GNS3, à partir d'un fichier d'intention JSON.

## Utilisation

```bash
python generate_conf.py intent_vrf.json
```

Les configs sont générées dans `configs_final/` sous la forme `i<number>_startup-config.cfg`.

Pour déployer directement dans GNS3 :

```bash
python drag_drop.py
```

## Fichiers d'intent

| Fichier | Description |
|---|---|
| `intent_vrf.json` | Topologie 3 AS avec MPLS, VRF, RSVP |
| `intent_basic.json` | Topologie simple MPLS/BGP |
| `intent_mpls_example.json` | MPLS avec plusieurs VRF clients |

## Structure du code

```
generate_conf.py      # point d'entrée
models.py             # dataclasses (Router, Interface, AutonomousSystem...)
parsing.py            # lecture du fichier JSON
addressing.py         # allocation des IPs (loopbacks, liens)
bgp.py                # construction des sessions BGP (iBGP, VPNv4, inter-AS)
generators/config.py  # génération des configs Cisco IOS
```

## Fonctionnalités supportées

- OSPF / RIPng
- BGP (iBGP full-mesh, route reflector, eBGP inter-AS)
- MPLS / LDP
- VRF + VPNv4
- RSVP / MPLS-TE
- IPv4 et IPv6
