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
    """Cherche le levé dans legacy/gis/ : .xlsx (prioritaire) ou .csv brut
    (export "Liste_coordonnees_BORNES", séparateur ';', colonnes MAT;X;Y;Z)."""
    if not GIS_DIR.exists():
        return None
    for ext in (".xlsx", ".csv"):
        for pattern in FICHIER_TOPO_PATTERNS + ["*polygo*", "*bornes*"]:
            pattern_re = pattern.replace("*", ".*")
            for f in sorted(GIS_DIR.iterdir()):
                if f.suffix.lower() == ext and re.match(pattern_re, f.stem, re.IGNORECASE):
                    return f
    return None


def vers_latlon(easting, northing):
    lon, lat = te._to_geo.transform(easting, northing)
    return [round(lon, 7), round(lat, 7)]


# ----------------------------------------------------------------------------
# GIRATOIRE D'AKOM II — points d'implantation fournis par l'équipe Topographie
# (fichier Points_Giratoire_Akom2.xlsx, coordonnées UTM 32N : la colonne
# « LATITUDE » contient en réalité l'Est (X) et « LONGITUDE » le Nord (Y)).
# Dans cette zone le levé par couples D/G s'interrompt (PK 80,424 -> 80,596) :
# le contour réel de l'emprise suit alors le giratoire et la branche nord.
# Ordre des bords (identifiés sur le plan des points) :
#   bord DROIT  : P1..P9, puis la branche nord P18..P33, puis P34..P40
#   bord GAUCHE : P17..P10, puis P51..P41
# (P53..P60 sont des points de fermeture/doublons internes, non utilisés.)
# ----------------------------------------------------------------------------
GIRATOIRE_DROIT = list(range(1, 10)) + list(range(18, 34)) + list(range(34, 41))
GIRATOIRE_GAUCHE = list(range(17, 9, -1)) + list(range(51, 40, -1))


def charger_giratoire():
    """Retourne {'D': [(E,N)...], 'G': [(E,N)...]} ou None si le fichier est absent."""
    import openpyxl
    cand = sorted(GIS_DIR.glob("*[Gg]iratoire*.xlsx")) if GIS_DIR.exists() else []
    if not cand:
        return None
    ws = openpyxl.load_workbook(cand[0], read_only=True, data_only=True).active
    pts = {}
    for r in list(ws.iter_rows(values_only=True))[1:]:
        if r and r[0] and r[1] is not None and r[2] is not None:
            pts[int(str(r[0]).strip().upper().lstrip("P"))] = (float(r[1]), float(r[2]))
    return {"D": [pts[i] for i in GIRATOIRE_DROIT if i in pts],
            "G": [pts[i] for i in GIRATOIRE_GAUCHE if i in pts], "fichier": cand[0].name}


def inserer_giratoire(pks, points, giratoire):
    """Insère les bords du giratoire dans les listes D/G du ruban, à l'endroit du
    trou du levé. Retourne (droit, gauche) en lon/lat, ou None si non applicable."""
    import math
    def proche(seq, cote, extremite):
        cible = seq[extremite]
        return min(range(len(pks)), key=lambda i: math.hypot(
            points[pks[i]][cote][0] - cible[0], points[pks[i]][cote][1] - cible[1]))
    res = {}
    for cote in ("D", "G"):
        seq = giratoire[cote]
        if len(seq) < 2:
            return None
        i0 = proche(seq, cote, 0)
        i1 = proche(seq, cote, -1)
        # le début doit se raccorder au PK i0 et la fin au PK suivant i0+1
        if i1 != i0 + 1:
            print(f"  ⚠ giratoire : raccordement côté {cote} incohérent (PK {pks[i0]/1000:.3f} -> "
                  f"{pks[i1]/1000:.3f}) — giratoire ignoré.")
            return None
        res[cote] = (i0, [vers_latlon(e, n) for e, n in seq])
    if res["D"][0] != res["G"][0]:
        print("  ⚠ giratoire : côtés D et G raccordés à des PK différents — ignoré.")
        return None
    return res


def main():
    fichier = trouver_fichier_topo()
    if not fichier:
        print(f"::error::Aucun fichier topographique (.xlsx ou .csv) trouvé dans {GIS_DIR}/ — "
              f"l'emprise ne peut pas être générée.")
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
        giratoire = charger_giratoire()
        n_giratoire = 0
        if giratoire:
            ins = inserer_giratoire(pks_complets, points, giratoire)
            if ins:
                i0 = ins["D"][0]
                cote_droit = cote_droit[:i0 + 1] + ins["D"][1] + cote_droit[i0 + 1:]
                cote_gauche = cote_gauche[:i0 + 1] + ins["G"][1] + cote_gauche[i0 + 1:]
                n_giratoire = len(ins["D"][1]) + len(ins["G"][1])
                print(f"  ✓ Giratoire d'Akom II intégré ({giratoire['fichier']}) : {n_giratoire} points, "
                      f"entre PK {pks_complets[i0]/1000:.3f} et {pks_complets[i0+1]/1000:.3f} km")
        anneau = cote_droit + list(reversed(cote_gauche)) + [cote_droit[0]]

        feature_emprise = {
            "type": "Feature",
            "properties": {
                "nom": "Emprise réelle RN17 (levé topographique — équipe Topographie)",
                "pk_min_km": round(pks_complets[0] / 1000.0, 3),
                "pk_max_km": round(pks_complets[-1] / 1000.0, 3),
                "nb_sections": len(pks_complets),
                "source_fichier": fichier.name,
                "giratoire_akom2_points": n_giratoire,
            },
            "geometry": {"type": "Polygon", "coordinates": [anneau]},
        }
        with open(OUT_EMPRISE, "w", encoding="utf-8") as f:
            json.dump({"type": "FeatureCollection", "features": [feature_emprise]}, f,
                      ensure_ascii=False, separators=(",", ":"))
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
                  ensure_ascii=False, separators=(",", ":"))
    print(f"  ✓ {OUT_AXE.name} : axe central généré ({len(ligne_axe)} points)")


if __name__ == "__main__":
    main()
