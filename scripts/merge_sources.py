#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
merge_sources.py — Fusionne les données Kobo (temps réel) et les données
papier historiques (masques de saisie + photos NoteCam), et calcule les
statistiques affichées sur le géoportail (effectifs par catégorie,
kilométrage couvert par l'équipe d'enquête).

À exécuter APRÈS kobo_sync.py et (si applicable) legacy_import.py.

Produit :
  - site/data/eak_par_final.geojson   (couche unique consommée par Leaflet)
  - site/data/eak_par_final.csv
  - site/data/eak_par_final.gpx
  - site/data/stats.json              (statistiques pour le tableau de bord)
"""
import csv
import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "site" / "data"

KOBO_CSV = DATA_DIR / "eak_par_principal.csv"
LEGACY_CSV = DATA_DIR / "legacy_principal.csv"
KOBO_MANIFEST_CSV = DATA_DIR / "eak_par_manifest_media.csv"
LEGACY_MANIFEST_CSV = DATA_DIR / "legacy_manifest_media.csv"

OUT_GEOJSON = DATA_DIR / "eak_par_final.geojson"
OUT_CSV = DATA_DIR / "eak_par_final.csv"
OUT_GPX = DATA_DIR / "eak_par_final.gpx"
OUT_STATS = DATA_DIR / "stats.json"


def read_csv_rows(path):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_pk(raw):
    """Convertit un PK routier en kilomètres décimaux.
    Formats supportés : '12+300' (notation chaînage routier), '12.3', '12300'."""
    if not raw:
        return None
    raw = str(raw).strip().replace(",", ".")
    m = re.match(r"^(\d+)\s*\+\s*(\d+)$", raw)
    if m:
        return float(m.group(1)) + float(m.group(2)) / 1000.0
    try:
        val = float(raw)
        # Si la valeur semble être en mètres (grand nombre), convertir en km
        return val / 1000.0 if val > 1000 else val
    except ValueError:
        return None


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


import difflib

# Liste canonique des villages du corridor RN17 (identique à celle utilisée
# dans build_xlsform.py pour la cascade Kobo Département/Arrondissement/Village).
VILLAGES_CANONIQUES = [
    "Adoum", "Ando'o", "Azem", "Bikou'ou", "Ebolowa Si II", "Engom I", "Engom II",
    "Engong", "Konda", "Meyo-Ville", "Mvieng", "Mvilla-Yemissem", "Nkoemvone",
    "Yem-Ndong", "Zingui", "Abovoumba", "Aloum I", "Aloum II", "Avelezok", "Biton",
    "Ekowong", "Elon", "Foulassi I", "Foulassi II", "Mefo", "Mfenda", "Nelefup",
    "Ngone", "Nkolenyeng", "Nkolenyeng Yemvang", "Nkoloveng", "Nkong", "Si Djakon",
    "Lendi", "Bidou II", "Pangou", "Nkolmbonda", "Bidou III", "Nko'olong",
    "Nlozock", "Afan Oveng", "Akom I", "Adjap", "Akom II Village", "Nnemeyong",
    "Biboulman", "Ebemvok", "Akom II Ville", "Nkonmekak", "Mbanga Yessok",
    "Nlomoto", "Nyabitande", "Assok I", "Fenda", "Ndjabilobe", "Akok", "Elone",
]


def normalize_village(raw):
    """Rapproche un nom de village brut (variantes orthographiques, chiffres
    arabes/romains, préfixe 'vlg_' des données Kobo...) de son nom canonique
    dans la liste des 58 villages du corridor, par similarité floue."""
    if not raw:
        return "Non renseigné"
    v = str(raw).strip()
    if v.lower().startswith("vlg_"):
        v = v[4:].replace("_", " ")
    # Harmonisation chiffres arabes <-> romains courants (I/1, II/2, III/3)
    v_norm = v
    for arabe, romain in [(" 1", " I"), (" 2", " II"), (" 3", " III")]:
        if v_norm.endswith(arabe):
            v_norm = v_norm[: -len(arabe)] + romain

    best, best_score = v.strip().title(), 0.0
    for canon in VILLAGES_CANONIQUES:
        score = difflib.SequenceMatcher(None, v_norm.lower(), canon.lower()).ratio()
        if score > best_score:
            best, best_score = canon, score
    return best if best_score >= 0.6 else v.strip().title()


def dedupe_kobo_vs_legacy(kobo_rows, legacy_rows):
    """Détecte les PAP présentes à la fois dans les données Kobo (temps réel)
    et dans les données papier historiques (même personne saisie deux fois :
    une fois sur papier, une fois re-vérifiée via Kobo). En cas de
    correspondance forte (même village + nom très similaire), la ligne
    papier est fusionnée dans la ligne Kobo (source de vérité la plus
    récente) plutôt que comptée une seconde fois.
    """
    DEDUPE_THRESHOLD = 0.72
    kept_legacy = []
    n_fusions = 0
    for lrow in legacy_rows:
        lv, ln = normalize_village(lrow.get("village")), lrow.get("nom_prenom_cm") or ""
        match = None
        for krow in kobo_rows:
            kv, kn = normalize_village(krow.get("village")), krow.get("nom_prenom_cm") or ""
            if kv != lv:
                continue
            score = difflib.SequenceMatcher(
                None, ln.lower().strip(), kn.lower().strip()
            ).ratio()
            if score >= DEDUPE_THRESHOLD:
                match = krow
                break
        if match:
            n_fusions += 1
            match["_a_egalement_une_fiche_papier"] = "oui"
            match.setdefault("source", "kobo")
            # Si Kobo n'a pas encore de photo/coordonnées mais que le papier en a, on complète
            if not match.get("latitude") and lrow.get("latitude"):
                match["latitude"], match["longitude"] = lrow["latitude"], lrow["longitude"]
            print(f"  ↳ Fusion : « {ln} » ({lv}) déjà présent côté Kobo — non recompté.")
        else:
            kept_legacy.append(lrow)

    if n_fusions:
        print(f"{n_fusions} PAP papier fusionnée(s) avec une entrée Kobo existante "
              f"(évite le double comptage).")
    return kept_legacy


def build_photo_lookup():
    """Regroupe toutes les photos (Kobo + papier historique) par uuid de
    soumission, pour les rattacher à chaque point avant export."""
    lookup = {}
    for path in (KOBO_MANIFEST_CSV, LEGACY_MANIFEST_CSV):
        for r in read_csv_rows(path):
            lookup.setdefault(r["_uuid"], []).append({
                "champ": r.get("champ"),
                "chemin": r.get("chemin_local"),
            })
    return lookup


def main():
    kobo_rows = read_csv_rows(KOBO_CSV)
    for r in kobo_rows:
        r["source"] = "kobo"
    legacy_rows = read_csv_rows(LEGACY_CSV)

    legacy_rows = dedupe_kobo_vs_legacy(kobo_rows, legacy_rows)
    all_rows = kobo_rows + legacy_rows

    photo_lookup = build_photo_lookup()
    for r in all_rows:
        photos = photo_lookup.get(r.get("_uuid"), [])
        r["nb_photos"] = len(photos)
        # Photo principale pour l'aperçu carte : priorité au portrait du
        # répondant, sinon la première photo disponible quelle qu'elle soit.
        principale = next((p["chemin"] for p in photos if p["champ"] == "photo_repondant"), None)
        r["photo_repondant"] = principale or (photos[0]["chemin"] if photos else None)
        # Liste complète (jusqu'à 8 photos) encodée en JSON pour permettre une
        # mini-galerie dans l'info-bulle Leaflet.
        r["photos_json"] = json.dumps(photos[:8], ensure_ascii=False)
    print(f"{len(kobo_rows)} soumission(s) Kobo + {len(legacy_rows)} fiche(s) papier "
          f"historique(s) = {len(all_rows)} au total")

    # --- Export CSV unifié ---
    if all_rows:
        keys = []
        for r in all_rows:
            for k in r:
                if k not in keys:
                    keys.append(k)
        with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(all_rows)

    # --- Export GeoJSON unifié ---
    features = []
    for r in all_rows:
        lat, lon = to_float(r.get("latitude")), to_float(r.get("longitude"))
        if lat is None or lon is None:
            continue
        props = {k: v for k, v in r.items() if k not in ("latitude", "longitude", "altitude")}
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        })
    with open(OUT_GEOJSON, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False, indent=2)
    print(f"  ✓ {OUT_GEOJSON.name} ({len(features)} points géolocalisés)")

    # --- Export GPX unifié ---
    body = []
    for r in all_rows:
        lat, lon = to_float(r.get("latitude")), to_float(r.get("longitude"))
        if lat is None or lon is None:
            continue
        name = (r.get("nom_prenom_cm") or r.get("_uuid") or "PAP").replace("&", "et")
        body.append(f'  <wpt lat="{lat}" lon="{lon}"><name>{name}</name></wpt>\n')
    with open(OUT_GPX, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1">\n')
        f.write("".join(body))
        f.write("</gpx>\n")
    print(f"  ✓ {OUT_GPX.name} ({len(body)} waypoints)")

    # =========================================================================
    # STATISTIQUES POUR LE TABLEAU DE BORD DU GÉOPORTAIL
    # =========================================================================
    stats = {
        "total_pap": len(all_rows),
        "par_type_fiche": {},
        "par_source": {},
        "par_village": {},
        "par_troncon": {},
        "kilometrage": {},
    }

    for r in all_rows:
        tf = r.get("type_fiche") or "non_renseigne"
        src = r.get("source") or "non_renseigne"
        vlg = normalize_village(r.get("village"))
        tr = r.get("troncon") or "non_renseigne"
        stats["par_type_fiche"][tf] = stats["par_type_fiche"].get(tf, 0) + 1
        stats["par_source"][src] = stats["par_source"].get(src, 0) + 1
        stats["par_village"][vlg] = stats["par_village"].get(vlg, 0) + 1
        stats["par_troncon"][tr] = stats["par_troncon"].get(tr, 0) + 1

    # Kilométrage couvert : on privilégie le PK calculé géométriquement par
    # calcul_pk_lineaire.py (projection sur le tracé RN17, fiable et disponible
    # pour toute PAP géolocalisée) ; à défaut, on retombe sur le PK déclaré à
    # la main par les enquêteurs (notation "12+300" ou décimale, plus rare et
    # moins fiable).
    pk_calcule_lookup = {}
    pk_calcule_path = DATA_DIR / "pk_calcule.csv"
    if pk_calcule_path.exists():
        for r in read_csv_rows(pk_calcule_path):
            if r.get("pk_fiable") == "True" and r.get("pk_calcule_km"):
                pk_calcule_lookup[r["_uuid"]] = float(r["pk_calcule_km"])

    pk_values = []
    n_calcule, n_declare = 0, 0
    for r in all_rows:
        if r.get("_uuid") in pk_calcule_lookup:
            pk_values.append(pk_calcule_lookup[r["_uuid"]])
            n_calcule += 1
        else:
            v = parse_pk(r.get("pk"))
            if v is not None:
                pk_values.append(v)
                n_declare += 1

    if pk_values:
        stats["kilometrage"] = {
            "pk_min_km": round(min(pk_values), 2),
            "pk_max_km": round(max(pk_values), 2),
            "etendue_km": round(max(pk_values) - min(pk_values), 2),
            "nb_points_avec_pk": len(pk_values),
            "nb_pk_calcule_geometriquement": n_calcule,
            "nb_pk_declare_manuellement": n_declare,
        }
    else:
        stats["kilometrage"] = {"pk_min_km": None, "pk_max_km": None,
                                  "etendue_km": None, "nb_points_avec_pk": 0,
                                  "nb_pk_calcule_geometriquement": 0, "nb_pk_declare_manuellement": 0}

    stats["nb_villages_couverts"] = len([v for v in stats["par_village"] if v != "non_renseigne"])

    with open(OUT_STATS, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"  ✓ {OUT_STATS.name}")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
