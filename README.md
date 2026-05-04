# NAS — Network Automation Scripts

Génère automatiquement les configs de démarrage Cisco IOS pour des topologies GNS3, à partir d'un fichier d'intention JSON.

## Utilisation

```bash
python generate_conf.py intent_vrf.json
```

Les configs sont générées dans `configs_final/` sous la forme `i<number>_startup-config.cfg`.

Pour déployer directement dans GNS3 :
> Il faut que les fichiers de configuration, ainsi que le fichier `drag_drop.py` soient dans le même dossier que le fichier `.gns3`

```bash
python drag_drop.py <file.gns3>
```

## Fichier d'intent

 `intent_vrf.json` : Topologie complète de tests 3 AS clients avec MPLS, VRF, RSVP, ...*

### Points clés & fonctionnalités avancées :

- Rôles & VRF : 

Chaque routeur est défini par son rôle (P, PE, CE). Les VRF (AS1) gèrent l'isolation via RD et RT (import/export).

- Ingress Traffic Engineering (TE) :

``ingress_for`` : Liste les interfaces à prioriser sur un voisin spécifique. Le script génère automatiquement les prefix-lists et route-maps avec des communautés BGP (ex: 1:100).

- Flexibilité des Interfaces :

``other_interfaces`` : Permet d'injecter des réseaux manuels (ex: ``172.16.x.x``) pour simuler des architectures clients.

- BGP & Automatisation :

Gestion du ``allow-as in`` (pour les sites distants sur le même AS).

- Internet services :

Gestion grâce au flag `internet_gateway` et à la vrf `INTERNET`.

- RSVP-TE :
flag `rsvp`.

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

- IPv4 
- OSPF 
- BGP (iBGP full-mesh, route reflector, eBGP inter-AS)
- MPLS / LDP
- VRF + VPNv4
- Site sharing among customer
- Internet Services
- Ingress TE services for multi-connected CE routers
- RSVP / MPLS-TE
