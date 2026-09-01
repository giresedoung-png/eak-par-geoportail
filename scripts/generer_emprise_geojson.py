#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generer_emprise_geojson.py — Emprise réelle de la RN17 (GeoJSON) pour le
géoportail, déduite EXCLUSIVEMENT du levé topographique d'implantation
(couples de points D/G par PK), et non plus d'un tracé OSM approximatif.

Construit un polygone en reliant les points D (droite) dans l'ordre
croissant des PK, puis les points G (gauche) en ordre décroissant — formant
un "ruban" fidèle aux limites réellement implantées sur le terrain (largeur
variable selon les courbes), plutôt qu'une largeur théorique uniforme.

Se met à jour automatiquement à chaque exécution du pipeline : il suffit de
déposer une version mise à jour (ou étendue) du fichier Excel topographique
dans legacy/gis/ — l'emprise affichée sur le géoportail reflète alors les
nouveaux couples de PK disponibles, sans autre intervention.

Sortie :
  - site/data/emprise_rn17.geojson  (polygone de l'emprise réelle)
  - site/data/axe_rn17.geojson      (ligne centrale, pour référence/PK)
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topo_emprise as te

BASE_DIR = Path(__file__).resolve().parent.parent
GIS_DIR = BASE_DIR / "legacy" / "gis"
DATA_DIR = BASE_DIR / "site" / "data"

FICHIER_TOPO_PATTERNS = ["*emprise*implantation*", "*implantation*emprise*", "*coordonnees*pk*"]

OUT_EMPRISE = DATA_DIR / "emprise_rn17.geojson"
OUT_AXE = DATA_DIR / "axe_rn17.geojson"


def trouver_fichier_topo():
    if not GIS_DIR.exists():
        return None
    for pattern in FICHIER_TOPO_PATTERNS:
        pattern_re = pattern.replace("*", ".*")
        for f in GIS_DIR.iterdir():
            if f.suffix.lower() == ".xlsx" and re.match(pattern_re, f.stem, re.IGNORECASE):
                return f
    return None


def vers_latlon(easting, northing):
    lon, lat = te._to_geo.transform(easting, northing)
    return [round(lon, 7), round(lat, 7)]


def main():
    fichier = trouver_fichier_topo()
    if not fichier:
        print(f"⚠ Aucun fichier topographique trouvé dans {GIS_DIR}/ — rien à générer.")
        return

    print(f"Chargement du levé topographique depuis {fichier.name}...")
    points = te.charger_points_topo(fichier)
    pks_tries = sorted(points.keys())
    print(f"  {len(pks_tries)} PK distincts relevés, de {pks_tries[0]/1000:.3f} km "
          f"à {pks_tries[-1]/1000:.3f} km")

    # Ne retient, pour le POLYGONE, que les PK où D ET G sont tous deux
    # disponibles — nécessaire pour un ruban propre et fermé. Les PK à un
    # seul côté disponible restent utilisés pour l'axe central ci-dessous.
    pks_complets = [pk for pk in pks_tries if "D" in points[pk] and "G" in points[pk]]
    n_incomplets = len(pks_tries) - len(pks_complets)
    if n_incomplets:
        print(f"  ⚠ {n_incomplets} PK avec un seul côté disponible (D ou G) — ignorés pour "
              f"la construction du polygone d'emprise (nécessite les deux côtés), mais "
              f"conservés pour l'axe central.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if len(pks_complets) >= 2:
        cote_droit = [vers_latlon(*points[pk]["D"][:2]) for pk in pks_complets]
        cote_gauche = [vers_latlon(*points[pk]["G"][:2]) for pk in pks_complets]

        # Anneau du polygone : côté droit du PK le plus petit au plus grand,
        # puis côté gauche du plus grand au plus petit (fermeture du ruban) —
        # exactement l'ordre demandé : "en partant du couple PK le plus petit
        # vers le plus grand".
        anneau = cote_droit + list(reversed(cote_gauche)) + [cote_droit[0]]

        feature_emprise = {
            "type": "Feature",
            "properties": {
                "nom": "Emprise réelle RN17 (levé topographique — équipe Topographie)",
                "pk_min_km": round(pks_complets[0] / 1000.0, 3),
                "pk_max_km": round(pks_complets[-1] / 1000.0, 3),
                "nb_sections": len(pks_complets),
                "source_fichier": fichier.name,
            },
            "geometry": {"type": "Polygon", "coordinates": [anneau]},
        }
        with open(OUT_EMPRISE, "w", encoding="utf-8") as f:
            json.dump({"type": "FeatureCollection", "features": [feature_emprise]}, f,
                      ensure_ascii=False, indent=2)
        print(f"\n  ✓ {OUT_EMPRISE.name} : emprise réelle générée, PK "
              f"{feature_emprise['properties']['pk_min_km']} → "
              f"{feature_emprise['properties']['pk_max_km']} km "
              f"({len(pks_complets)} sections D/G)")
    else:
        print("\n⚠ Pas assez de PK avec D et G disponibles pour construire le polygone d'emprise.")

    # --- Axe central (ligne de référence), sur l'ensemble des PK disponibles
    # (D et/ou G, y compris les PK à un seul côté) — utile pour le repérage
    # visuel du PK sur la carte, indépendamment du polygone d'emprise. ---
    axe = te.construire_axe(points)
    ligne_axe = [vers_latlon(e, n) for _, e, n, _ in axe]
    feature_axe = {
        "type": "Feature",
        "properties": {
            "nom": "Axe RN17 (levé topographique)",
            "pk_min_km": round(pks_tries[0] / 1000.0, 3),
            "pk_max_km": round(pks_tries[-1] / 1000.0, 3),
        },
        "geometry": {"type": "LineString", "coordinates": ligne_axe},
    }
    with open(OUT_AXE, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": [feature_axe]}, f,
                  ensure_ascii=False, indent=2)
    print(f"  ✓ {OUT_AXE.name} : axe central généré ({len(ligne_axe)} points)")


if __name__ == "__main__":
    main()
