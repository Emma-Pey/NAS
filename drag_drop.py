import json
import os
import shutil

# Récupération des noms des dossiers où les configs doivent être placées
# A MODIFIER : nom du fichier gns3
with open('3AS_GNS3/3AS_GNS3.gns3', 'r', encoding='utf-8') as f:
    data = json.load(f)

folders = {}
for node in data['topology']['nodes']:
    name = node['name']
    node_id = node['node_id']
    dynamips_id = node.get('properties', {}).get('dynamips_id', 1)
    folders[name] = (node_id, dynamips_id)
        
# A MODIFIER : dossier source
SOURCE_CFG_DIR = "configs" # Dossier où le script de génération a déposé les fichiers de config

GNS3_PROJECT_ROOT = "3AS_GNS3" # Chemin vers le répertoire racine du projet GNS3 où se trouvent 'project-files/dynamips'

def run_drag_and_drop_bot():
    print("Début du déploiement des configurations...")
    
    # On parcourt les routeurs extraits dans 'folders'
    for name, (node_id, dynamips_id) in folders.items():
        # Fichier source généré
        source_file = os.path.join(SOURCE_CFG_DIR, f"{name}_startup-config.cfg")

        # Vérifier si le fichier généré existe bien
        if os.path.exists(source_file):
            target_path = os.path.join(GNS3_PROJECT_ROOT, "project-files", "dynamips", node_id, "configs", f"i{dynamips_id}_startup-config.cfg")

            try:
                # Créer le dossier de destination s'il n'existe pas
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                
                # Copie effective du fichier 
                shutil.copy(source_file, target_path)
                print(f" {name} : Config copiée vers {node_id}")
            except Exception as e:
                print(f" Erreur pour {name} ({node_id}) : {e}")
        else:
            print(f" Fichier introuvable pour {name}")

if __name__ == "__main__":
    run_drag_and_drop_bot()
    print("Déploiement terminé")
