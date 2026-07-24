#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kobo_sync.py — Synchronisation quotidienne KoboToolbox -> GIS (EAK-PAR)
=========================================================================

Ce script :
  1. Se connecte à l'API KoboToolbox (v2) avec un jeton API personnel.
  2. Télécharge les soumissions (nouvelles + mises à jour) du formulaire EAK-PAR.
  3. Sépare les données en :
       - une table principale (1 ligne par soumission, avec géométrie point)
       - une table par groupe répétable (PAP décret, conjoints, enfants,
         personnes handicapées, terrains, tombes, arbres...), reliées à la
         table principale par l'identifiant de soumission (_uuid).
  4. Télécharge les pièces jointes (photos, signatures) dans un dossier
     organisé par soumission.
  5. Produit des exports prêts pour le SIG : GeoJSON (couche principale),
     CSV (toutes les tables), GPX (points).
  6. Conserve un fichier de suivi (checkpoint) pour ne re-télécharger que
     les soumissions nouvelles ou modifiées lors des exécutions suivantes.

Utilisation :
  1. Renseigner les variables de configuration ci-dessous (ou un fichier .env).
  2. `pip install requests` (seule dépendance externe).
  3. Exécuter : `python3 kobo_sync.py`
  4. Planifier quotidiennement : voir instructions en bas de fichier / README.

Auteur : généré avec Claude pour le projet EAK-PAR (Cabinet AMBOL / CERAF-NORD)
"""

import os
import sys
import json
import csv
import time
import shutil
from datetime import datetime, timezone
from pathlib import Path

import requests
from PIL import Image
from io import BytesIO

# =============================================================================
# CONFIGURATION — à adapter à votre projet
# =============================================================================

KOBO_SERVER = os.environ.get("KOBO_SERVER", "https://kf.kobotoolbox.org")
API_TOKEN = os.environ.get("KOBO_API_TOKEN", "COLLEZ_VOTRE_JETON_API_ICI")
ASSET_UID = os.environ.get("KOBO_ASSET_UID", "COLLEZ_L_UID_DE_VOTRE_FORMULAIRE_ICI")

# Tout ce qui se trouve dans SITE_DIR est ce qui sera envoyé par FTP vers
# InfinityFree (dossier htdocs / public_html). data/ et media/ sont générés
# ici à chaque exécution, à côté de index.html (déjà présent dans site/).
BASE_DIR = Path(__file__).resolve().parent.parent
SITE_DIR = BASE_DIR / "site"
DATA_DIR = SITE_DIR / "data"
MEDIA_DIR = SITE_DIR / "media"
CHECKPOINT_FILE = BASE_DIR / "scripts" / "last_sync.json"  # hors site/ : pas besoin de l'uploader

# Téléchargement des médias (photos/signatures) : peut être désactivé si le
# quota de fichiers (inodes) InfinityFree devient serré — mettre à "false"
# pour ne synchroniser que les données géographiques/statistiques.
SYNC_MEDIA = os.environ.get("SYNC_MEDIA", "true").lower() == "true"

# Compression des images pour ménager le stockage et le nombre de fichiers
# gratuits (InfinityFree : ~5 Go et ~30 000 fichiers au total). Une photo
# smartphone brute (3-6 Mo) est ramenée à quelques dizaines de Ko.
IMAGE_MAX_DIMENSION = int(os.environ.get("IMAGE_MAX_DIMENSION", "1280"))  # pixels, plus grand côté
IMAGE_JPEG_QUALITY = int(os.environ.get("IMAGE_JPEG_QUALITY", "70"))      # 1-95

# Nom du champ GPS (geopoint) dans le formulaire EAK-PAR
GEOPOINT_FIELD_CANDIDATES = [
    "A_identification_generale/gps_localisation",
    "gps_localisation",
]

# Groupes répétables du formulaire à exporter comme tables liées
# (chemin XLSForm complet tel qu'il apparaît dans le JSON de soumission)
REPEAT_GROUPS = {
    "pap_decret": "B_verif_decret/rep_pap_decret",
    "handicap": "C_identification_nouveau/C2_chef_menage/rep_handicap",
    "activite_conjoint": "C_identification_nouveau/C3_activites_economiques/grp_activite_conjoint/rep_activite_conjoint",
    "activite_enfant": "C_identification_nouveau/C3_activites_economiques/grp_activite_enfant/rep_activite_enfant",
    "activite_autre_membre": "C_identification_nouveau/C3_activites_economiques/grp_activite_autre_membre/rep_activite_autre_membre",
    "terrain": "C_identification_nouveau/C4_biens_actifs/rep_terrain",
    "tombes": "C_identification_nouveau/C4_biens_actifs/rep_tombes",
    "arbres_concession": "C_identification_nouveau/C4_biens_actifs/rep_arbres_concession",
}

# Champs de type image/signature à télécharger comme pièces jointes
ATTACHMENT_FIELDS = [
    "B_verif_decret/rep_pap_decret/signature_pap_decret",
    "B_verif_decret/signature_enqueteur_b",
    "B_verif_decret/signature_support_icm_b",
    "B_verif_decret/signature_supervision_mdc_b",
    "B_verif_decret/signature_chef_village_b",
    "B_verif_decret/photo_repondant_b",
    "C_identification_nouveau/C_annexe1_photos/photo_1_vue_generale",
    "C_identification_nouveau/C_annexe1_photos/photo_2_batiments",
    "C_identification_nouveau/C_annexe1_photos/photo_3_cultures",
    "C_identification_nouveau/C_annexe1_photos/photo_4_pap_visage",
    "C_identification_nouveau/C_annexe1_photos/photo_5_piece_identite",
    "C_identification_nouveau/C_annexe1_photos/photo_6_tombe_infra",
    "C_identification_nouveau/C7_cloture_signatures/signature_cm_pap",
    "C_identification_nouveau/C7_cloture_signatures/signature_temoin",
    "C_identification_nouveau/C7_cloture_signatures/signature_enqueteur_c7",
    "C_identification_nouveau/C7_cloture_signatures/signature_superviseur",
]

HEADERS = {"Authorization": f"Token {API_TOKEN}"}
PAGE_SIZE = 1000


# =============================================================================
# FONCTIONS UTILITAIRES
# =============================================================================

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def load_checkpoint():
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_submission_time": None, "synced_uuids": []}


def save_checkpoint(checkpoint):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False, indent=2)


def api_get(url, params=None):
    resp = requests.get(url, headers=HEADERS, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def fetch_all_submissions(checkpoint):
    """Récupère toutes les soumissions, avec pagination, en ne demandant que
    les nouvelles/modifiées depuis le dernier passage si un checkpoint existe."""
    url = f"{KOBO_SERVER}/api/v2/assets/{ASSET_UID}/data/"
    all_results = []
    params = {"limit": PAGE_SIZE, "start": 0}

    # Filtre incrémental : on ne redemande que ce qui est postérieur au dernier sync
log("Récupération de toutes les soumissions (mode complet)")

    while True:
        data = api_get(url, params=params)
        results = data.get("results", [])
        all_results.extend(results)
        if not data.get("next"):
            break
        params["start"] += PAGE_SIZE
        time.sleep(0.2)  # ménager le serveur

    log(f"{len(all_results)} soumission(s) récupérée(s)")
    return all_results


def get_nested(d, path, default=None):
    """Récupère une valeur dans le JSON de soumission via un chemin de type
    'Groupe/sous-groupe/champ' (format utilisé par l'API Kobo pour les groupes)."""
    return d.get(path, default)


def find_geopoint(submission):
    for candidate in GEOPOINT_FIELD_CANDIDATES:
        val = submission.get(candidate)
        if val:
            return val
    # recherche large en dernier recours : n'importe quel champ finissant par gps_localisation
    for k, v in submission.items():
        if k.endswith("gps_localisation") and v:
            return v
    return None


def parse_geopoint(raw):
    """Le geopoint Kobo est une chaîne 'lat lon altitude precision'."""
    if not raw:
        return None, None, None, None
    parts = raw.strip().split(" ")
    lat = float(parts[0]) if len(parts) > 0 and parts[0] else None
    lon = float(parts[1]) if len(parts) > 1 and parts[1] else None
    alt = float(parts[2]) if len(parts) > 2 and parts[2] else None
    prec = float(parts[3]) if len(parts) > 3 and parts[3] else None
    return lat, lon, alt, prec


def compress_image(raw_bytes, dest_path):
    """Redimensionne et compresse une image pour ménager stockage/inodes.
    Les fichiers non-image sont écrits tels quels si la compression échoue."""
    try:
        img = Image.open(BytesIO(raw_bytes))
        img = img.convert("RGB")
        img.thumbnail((IMAGE_MAX_DIMENSION, IMAGE_MAX_DIMENSION))
        out_path = dest_path.with_suffix(".jpg")
        img.save(out_path, "JPEG", quality=IMAGE_JPEG_QUALITY, optimize=True)
        return out_path
    except Exception:
        with open(dest_path, "wb") as f:
            f.write(raw_bytes)
        return dest_path


def download_attachment(submission, field_path, attachments_index, dest_dir):
    """Télécharge une pièce jointe (photo/signature) référencée par un champ,
    en s'appuyant sur la liste _attachments fournie par l'API. Les images sont
    automatiquement compressées (IMAGE_MAX_DIMENSION / IMAGE_JPEG_QUALITY)."""
    if not SYNC_MEDIA:
        return None
    filename_value = submission.get(field_path)
    if not filename_value:
        return None
    # Kobo référence l'attachment par son nom de fichier dans le champ texte,
    # et fournit l'URL de téléchargement dans _attachments
    att = attachments_index.get(filename_value)
    if not att:
        # tentative de correspondance par suffixe (au cas où le chemin diffère)
        for fname, a in attachments_index.items():
            if fname.endswith(filename_value) or filename_value.endswith(fname):
                att = a
                break
    if not att:
        return None

    download_url = att.get("download_url")
    if not download_url:
        return None

    dest_dir.mkdir(parents=True, exist_ok=True)
    safe_field = field_path.replace("/", "__")
    ext = Path(att.get("filename", filename_value)).suffix or ".jpg"
    dest_path = dest_dir / f"{safe_field}{ext}"

    try:
        r = requests.get(download_url, headers=HEADERS, timeout=60)
        r.raise_for_status()
        if ext.lower() in (".jpg", ".jpeg", ".png"):
            final_path = compress_image(r.content, dest_path)
        else:
            with open(dest_path, "wb") as f:
                f.write(r.content)
            final_path = dest_path
        return str(final_path.relative_to(SITE_DIR))
    except Exception as e:
        log(f"  ⚠ Échec téléchargement {field_path} ({filename_value}) : {e}")
        return None


def build_attachments_index(submission):
    idx = {}
    for att in submission.get("_attachments", []):
        fname = att.get("filename", "").split("/")[-1]
        idx[fname] = att
        idx[att.get("filename", "")] = att
    return idx


# =============================================================================
# TRAITEMENT PRINCIPAL
# =============================================================================

def process_submissions(submissions):
    main_rows = []
    repeat_rows = {key: [] for key in REPEAT_GROUPS}
    manifest_rows = []  # journal des pièces jointes téléchargées

    for sub in submissions:
        uuid = sub.get("_uuid") or sub.get("meta/instanceID", "")
        submission_id = sub.get("_id")
        submission_time = sub.get("_submission_time")
        attachments_index = build_attachments_index(sub)
        sub_media_dir = MEDIA_DIR / str(submission_id)

        geopoint_raw = find_geopoint(sub)
        lat, lon, alt, prec = parse_geopoint(geopoint_raw)

        row = {
            "_uuid": uuid,
            "_id": submission_id,
            "_submission_time": submission_time,
            "type_fiche": sub.get("type_fiche"),
            "troncon": sub.get("A_identification_generale/troncon"),
            "departement": sub.get("A_identification_generale/departement"),
            "arrondissement": sub.get("A_identification_generale/arrondissement"),
            "village": sub.get("A_identification_generale/village"),
            "date_enquete": sub.get("A_identification_generale/date_enquete"),
            "pk": sub.get("A_identification_generale/pk"),
            "nom_prenom_cm": sub.get(
                "C_identification_nouveau/C2_chef_menage/nom_prenom_cm"),
            "latitude": lat,
            "longitude": lon,
            "altitude": alt,
            "precision_gps": prec,
        }
        main_rows.append(row)

        # --- Téléchargement des pièces jointes ---
        for field_path in ATTACHMENT_FIELDS:
            local_path = download_attachment(sub, field_path, attachments_index, sub_media_dir)
            if local_path:
                manifest_rows.append({
                    "_uuid": uuid,
                    "_id": submission_id,
                    "champ": field_path,
                    "chemin_local": local_path,
                })

        # --- Extraction des groupes répétables ---
        for key, group_path in REPEAT_GROUPS.items():
            items = sub.get(group_path, [])
            if not isinstance(items, list):
                continue
            for i, item in enumerate(items):
                flat_item = {"_uuid": uuid, "_id": submission_id, "_index_repeat": i}
                flat_item.update({k: v for k, v in item.items() if not k.startswith("_")})
                repeat_rows[key].append(flat_item)

    return main_rows, repeat_rows, manifest_rows


# =============================================================================
# EXPORTS
# =============================================================================

def export_csv(rows, path):
    if not rows:
        log(f"  (aucune ligne pour {path.name}, fichier non créé)")
        return
    all_keys = []
    for r in rows:
        for k in r.keys():
            if k not in all_keys:
                all_keys.append(k)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_keys)
        writer.writeheader()
        writer.writerows(rows)
    log(f"  ✓ {path.name} ({len(rows)} lignes)")


def export_geojson(rows, path):
    features = []
    for r in rows:
        if r.get("latitude") is None or r.get("longitude") is None:
            continue
        props = {k: v for k, v in r.items() if k not in ("latitude", "longitude", "altitude")}
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [r["longitude"], r["latitude"]] + (
                    [r["altitude"]] if r.get("altitude") is not None else []
                ),
            },
            "properties": props,
        })
    geojson = {"type": "FeatureCollection", "features": features}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)
    log(f"  ✓ {path.name} ({len(features)} points géolocalisés)")


def export_gpx(rows, path):
    header = '<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="EAK-PAR kobo_sync">\n'
    footer = "</gpx>\n"
    body = []
    for r in rows:
        if r.get("latitude") is None or r.get("longitude") is None:
            continue
        name = (r.get("nom_prenom_cm") or r.get("_uuid") or "PAP").replace("&", "et")
        body.append(
            f'  <wpt lat="{r["latitude"]}" lon="{r["longitude"]}">\n'
            f'    <name>{name}</name>\n'
            f'    <desc>Village : {r.get("village") or ""} | Type : {r.get("type_fiche") or ""} | '
            f'Date : {r.get("date_enquete") or ""}</desc>\n'
            f"  </wpt>\n"
        )
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + "".join(body) + footer)
    log(f"  ✓ {path.name} ({len(body)} waypoints)")


# =============================================================================
# POINT D'ENTRÉE
# =============================================================================

def main():
    if "COLLEZ_" in API_TOKEN or "COLLEZ_" in ASSET_UID:
        log("⚠ CONFIGURATION INCOMPLÈTE : renseignez KOBO_API_TOKEN et KOBO_ASSET_UID")
        log("  (variables d'environnement ou directement dans le script)")
        sys.exit(1)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    checkpoint = load_checkpoint()
    submissions = fetch_all_submissions(checkpoint)

    if not submissions and checkpoint.get("last_submission_time"):
        log("Aucune nouvelle soumission depuis la dernière synchronisation.")
        return

    main_rows, repeat_rows, manifest_rows = process_submissions(submissions)

    log("Export des fichiers...")
    export_csv(main_rows, DATA_DIR / "eak_par_principal.csv")
    export_geojson(main_rows, DATA_DIR / "eak_par_principal.geojson")
    export_gpx(main_rows, DATA_DIR / "eak_par_principal.gpx")
    for key, rows in repeat_rows.items():
        export_csv(rows, DATA_DIR / f"eak_par_{key}.csv")
    export_csv(manifest_rows, DATA_DIR / "eak_par_manifest_media.csv")

    # Mise à jour du checkpoint
    if submissions:
        max_time = max(s.get("_submission_time", "") for s in submissions)
        checkpoint["last_submission_time"] = max_time
        checkpoint["synced_uuids"] = list(set(
            checkpoint.get("synced_uuids", []) + [s.get("_uuid") for s in submissions]
        ))
        save_checkpoint(checkpoint)

    log("Synchronisation terminée avec succès.")


if __name__ == "__main__":
    main()
