#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calcul_pk_lineaire.py — Référencement linéaire (chaînage) sur le tracé RN17
=============================================================================

Calcule le PK (point kilométrique) de chaque PAP géolocalisée par
PROJECTION GÉOMÉTRIQUE sur le tracé réel de la route, plutôt que de
dépendre du PK saisi manuellement par les enquêteurs (souvent absent).

Entrées attendues (déposées dans legacy/gis/) :
  - Le linéaire RN17 : un fichier de tracé (ligne) — Shapefile (.shp + .dbf +
    .shx + .prj), GeoJSON (.geojson), KML (.kml) ou GPX piste (.gpx).
  - Les villages : un fichier de points avec au moins un champ "nom" —
    mêmes formats acceptés, ou simple CSV/Excel avec colonnes
    nom/latitude/longitude.

Sortie :
  - site/data/pk_calcule.csv           (PK calculé par PAP, distance à l'axe)
  - site/data/villages_pk.csv          (PK calculé par village, pour recalage)
  - Le PK calculé est ensuite intégré par merge_sources.py à la place (ou en
    complément) du PK déclaré, pour un kilométrage couvert beaucoup plus fiable.

Dépendances : pip install shapely pyproj geopandas fiona
"""
import csv
import json
import re
import unicodedata
import difflib
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point, LineString
from shapely.ops import transform, linemerge
import pyproj

BASE_DIR = Path(__file__).resolve().parent.parent
GIS_DIR = BASE_DIR / "legacy" / "gis"
LIGNE_RN17_PATTERNS = ["*lineaire*rn17*", "*rn17*lineaire*", "*rn17*"]
VILLAGES_PATTERNS = ["*village*"]

DATA_DIR = BASE_DIR / "site" / "data"
OUT_PK_PAP = DATA_DIR / "pk_calcule.csv"
OUT_PK_VILLAGES = DATA_DIR / "villages_pk.csv"

# Seuil (mètres) au-delà duquel un point est jugé trop éloigné du tracé pour
# qu'un PK lui soit calculé de façon fiable (probable erreur GPS ou parcelle
# réellement hors emprise).
DISTANCE_MAX_PLAUSIBLE_M = 2000

# Tolérance (mètres) pour recoller deux segments de route dont les extrémités
# ne se touchent pas exactement (écarts de calage courants dans les exports
# OSM) — augmentez si votre fichier source présente des écarts plus larges
# mais toujours fiables (véritable continuité de la route).
STITCH_TOLERANCE_M = 300

# Nom (ou fragment de nom) des deux localités bornant le corridor, utilisés
# pour orienter automatiquement le PK dans le bon sens (PK 0 = Ebolowa,
# confirmé par l'équipe topographique — et non Kribi).
REFERENCE_PK0 = "Ebolowa"
REFERENCE_PK_FIN = "Kribi"

# Liste officielle des 58 villages figurant dans les deux décrets
# d'indemnisation (N°2022/3973/PM - Mvila, et N°2023/00018/PM - Océan) —
# identique à celle utilisée dans merge_sources.py et dans le formulaire
# Kobo. Seuls les villages du fichier Villages.zip qui correspondent à
# cette liste ET qui sont géométriquement proches du tracé sont retenus.
VILLAGES_DECRETS = [
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

# Seuil de similarité (0-1) pour rapprocher un nom de village du fichier SIG
# (variantes orthographiques possibles) d'un nom officiel des décrets.
SEUIL_CORRESPONDANCE_VILLAGE = 0.6


def _sans_accents_simple(s):
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()


def _extraire_suffixe_numerique(s):
    """Extrait un éventuel suffixe numérique (chiffre arabe ou romain I/II/III)
    en fin de nom, pour éviter les confusions du type 'Akom I' / 'Akom II'
    lors de la correspondance floue (qui, sans cette vérification, jugerait
    ces deux noms quasi identiques par simple ratio de caractères)."""
    m = re.search(r"\b(i{1,3}|1|2|3)\s*$", s.strip(), re.IGNORECASE)
    if not m:
        return None
    val = m.group(1).lower()
    return {"i": 1, "1": 1, "ii": 2, "2": 2, "iii": 3, "3": 3}.get(val)


def correspond_a_un_village_decret(nom_village):
    """Vérifie si un nom de village (issu du fichier SIG) correspond, par
    similarité floue, à l'un des 58 villages officiels des deux décrets.
    Retourne le nom canonique du décret le plus proche si trouvé, sinon None.
    Les suffixes numériques (I/II/III, 1/2/3) doivent correspondre
    exactement quand les deux noms en comportent un, pour éviter les
    confusions (ex. 'Akom II' ne doit pas matcher 'Akom I')."""
    if not nom_village or str(nom_village).lower() == "nan":
        return None
    n = _sans_accents_simple(nom_village)
    suffixe_source = _extraire_suffixe_numerique(n)
    tokens_source = set(re.sub(r"[^a-z0-9\s]", "", n).split())
    best, best_score = None, 0.0
    for canon in VILLAGES_DECRETS:
        canon_norm = _sans_accents_simple(canon)
        suffixe_canon = _extraire_suffixe_numerique(canon_norm)
        if suffixe_source is not None and suffixe_canon is not None and suffixe_source != suffixe_canon:
            continue  # ex. "Akom II" ne doit jamais matcher "Akom I"
        tokens_canon = set(re.sub(r"[^a-z0-9\s]", "", canon_norm).split())
        char_ratio = difflib.SequenceMatcher(None, n, canon_norm).ratio()
        # Le "mot de base" (ex. "akom" dans "akom ii") doit être commun aux
        # deux noms — sans ce critère, "Akom II" matcherait à tort "Aloum II"
        # (même longueur, ratio de caractères trompeusement élevé).
        tokens_non_numeriques_source = {t for t in tokens_source if not t.isdigit() and t not in ("i", "ii", "iii")}
        tokens_non_numeriques_canon = {t for t in tokens_canon if not t.isdigit() and t not in ("i", "ii", "iii")}
        # Le "mot de base" doit être commun aux deux noms — exactement, ou à
        # forte similarité de caractères (pour tolérer les variantes
        # orthographiques type "Nelefup"/"Nnelefoup") — sans ce critère,
        # "Akom II" matcherait à tort "Aloum II" (ratio global trompeur).
        mot_de_base_commun = any(
            difflib.SequenceMatcher(None, ts, tc).ratio() >= 0.75
            for ts in tokens_non_numeriques_source for tc in tokens_non_numeriques_canon
        )
        if not mot_de_base_commun:
            continue
        score = char_ratio
        if score > best_score:
            best, best_score = canon, score
    return best if best_score >= SEUIL_CORRESPONDANCE_VILLAGE else None

# Projection adaptée au Cameroun (UTM zone 32N, EPSG:32632) pour des calculs
# de distance en mètres corrects (les degrés lat/lon ne le permettent pas
# directement). Ajustez si votre corridor est en zone 33N.
CRS_PROJETE = "EPSG:32632"
CRS_GEO = "EPSG:4326"


EXTENSIONS_ACCEPTEES = (".geojson", ".json", ".shp", ".kml", ".gpx", ".csv", ".xlsx")


def _sans_accents(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def find_first_existing(patterns):
    """Recherche insensible à la casse ET aux accents d'un fichier SIG dans
    GIS_DIR, en acceptant plusieurs formats et variantes de nommage (ex.
    'Linéaire_RN17.shp' ou 'Villages.shp' plutôt que le nom exact attendu)."""
    if not GIS_DIR.exists():
        return None
    all_files = list(GIS_DIR.iterdir())
    for pattern in patterns:
        pattern_re = pattern.replace("*", ".*")
        for f in all_files:
            if f.suffix.lower() in EXTENSIONS_ACCEPTEES and re.match(
                pattern_re, _sans_accents(f.stem), re.IGNORECASE
            ):
                return f
    return None


def stitch_segments(segments, tolerance_m=300):
    """Recolle des segments de ligne dont les extrémités sont proches (mais
    pas exactement identiques — cas fréquent des exports OSM, où chaque
    tronçon est digitalisé séparément avec de petits écarts de calage).
    À chaque itération, fusionne la paire d'extrémités la plus proche parmi
    tous les segments restants, tant que cette distance reste sous le seuil
    de tolérance (en mètres, dans le CRS projeté)."""
    segs = [list(s.coords) for s in segments]
    while len(segs) > 1:
        best_dist, best_pair, best_config = None, None, None
        for i in range(len(segs)):
            for j in range(len(segs)):
                if i == j:
                    continue
                a_end = Point(segs[i][-1])
                b_start, b_end = Point(segs[j][0]), Point(segs[j][-1])
                d_end_start = a_end.distance(b_start)
                d_end_end = a_end.distance(b_end)
                if best_dist is None or d_end_start < best_dist:
                    best_dist, best_pair, best_config = d_end_start, (i, j), "end_to_start"
                if d_end_end < best_dist:
                    best_dist, best_pair, best_config = d_end_end, (i, j), "end_to_end"
        if best_dist is None or best_dist > tolerance_m:
            break  # écart trop important pour être recollé sans risque
        i, j = best_pair
        nouveau = segs[i] + (segs[j] if best_config == "end_to_start" else list(reversed(segs[j])))
        segs = [s for k, s in enumerate(segs) if k not in (i, j)] + [nouveau]
    return [LineString(s) for s in segs]


def orienter_ligne(line, villages_gdf):
    """Réoriente la ligne (si besoin) pour que le PK 0 corresponde à
    REFERENCE_PK0 (Ebolowa, confirmé par l'équipe topographique) plutôt
    qu'à l'autre extrémité (Kribi). Sans quoi, le sens du PK dépend
    arbitrairement de l'ordre des points dans le fichier source."""
    if villages_gdf is None:
        print(f"  ⚠ Aucune couche de villages disponible pour orienter le PK — "
              f"orientation non vérifiée (risque de PK inversé).")
        return line

    def find_village(nom_cherche):
        matches = villages_gdf[villages_gdf["nom"].astype(str).str.contains(
            nom_cherche, case=False, na=False, regex=False)]
        return matches.iloc[0].geometry if len(matches) else None

    pt_debut = find_village(REFERENCE_PK0)
    pt_fin = find_village(REFERENCE_PK_FIN)
    if pt_debut is None or pt_fin is None:
        print(f"  ⚠ Impossible de repérer « {REFERENCE_PK0} » et/ou « {REFERENCE_PK_FIN} » "
              f"dans la couche de villages pour vérifier l'orientation du PK — orientation "
              f"non garantie.")
        return line

    pk_debut, pk_fin = line.project(pt_debut), line.project(pt_fin)
    if pk_debut > pk_fin:
        print(f"  Orientation du tracé inversée : PK 0 fixé à {REFERENCE_PK0} "
              f"(au lieu de {REFERENCE_PK_FIN}), conformément à la confirmation de "
              f"l'équipe topographique.")
        return LineString(list(line.coords)[::-1])
    print(f"  Orientation du tracé déjà correcte : PK 0 = {REFERENCE_PK0}.")
    return line


def load_line(path):
    """Charge le tracé RN17 comme une unique LineString : fusionne d'abord
    les segments strictement connectés, puis recolle les segments proches
    (écarts de calage courants dans les exports OSM) via stitch_segments()."""
    gdf = gpd.read_file(path)
    gdf = gdf.to_crs(CRS_PROJETE)
    geoms = list(gdf.geometry)
    merged = linemerge(geoms) if len(geoms) > 1 else geoms[0]
    parts = list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]

    if len(parts) > 1:
        print(f"  {len(parts)} segment(s) après fusion stricte — tentative de recollage "
              f"des écarts (tolérance {STITCH_TOLERANCE_M} m)...")
        parts = stitch_segments(parts, tolerance_m=STITCH_TOLERANCE_M)

    if len(parts) == 1:
        return parts[0]

    parts.sort(key=lambda g: -g.length)
    total_recolle = parts[0].length
    print(f"  ⚠ Le tracé reste fragmenté en {len(parts)} segments après recollage — "
          f"écarts trop importants (> {STITCH_TOLERANCE_M} m) pour être comblés automatiquement. "
          f"Segment principal retenu : {total_recolle/1000:.1f} km. Vérifiez la continuité du "
          f"fichier source, ou augmentez STITCH_TOLERANCE_M si l'écart est fiable/normal.")
    return parts[0]


def _reparer_mojibake(s):
    """Corrige un cas fréquent de double encodage UTF-8/Latin-1 rencontré
    dans les attributs de Shapefile sans .cpg correct (ex. 'DikobÃ©' au lieu
    de 'Dikobé'). Ne modifie pas la chaîne si elle est déjà correcte."""
    if not isinstance(s, str):
        return s
    try:
        return s.encode("latin1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return s


def load_points(path):
    """Charge une couche de points (villages) avec son nom, quel que soit le
    format d'entrée (SIG classique ou tableur avec colonnes lat/lon)."""
    if path.suffix.lower() in (".csv", ".xlsx"):
        import pandas as pd
        df = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_excel(path)
        cols_lower = {c.lower(): c for c in df.columns}
        col_nom = next((cols_lower[c] for c in cols_lower if "nom" in c or "village" in c or "name" in c), df.columns[0])
        col_lat = next((cols_lower[c] for c in cols_lower if "lat" in c), None)
        col_lon = next((cols_lower[c] for c in cols_lower if "lon" in c), None)
        gdf = gpd.GeoDataFrame(
            df, geometry=gpd.points_from_xy(df[col_lon], df[col_lat]), crs=CRS_GEO
        )
        gdf = gdf.rename(columns={col_nom: "nom"})
    else:
        gdf = gpd.read_file(path)
        col_nom = next((c for c in gdf.columns if "nom" in c.lower() or "village" in c.lower() or "name" in c.lower()), None)
        if col_nom:
            gdf = gdf.rename(columns={col_nom: "nom"})
    if "nom" in gdf.columns:
        gdf["nom"] = gdf["nom"].apply(_reparer_mojibake)
    return gdf.to_crs(CRS_PROJETE)


def project_point_on_line(line, point_geo):
    """Projette un point (en coordonnées géographiques lat/lon) sur le
    tracé (en coordonnées projetées), et retourne (pk_km, distance_axe_m)."""
    project = pyproj.Transformer.from_crs(CRS_GEO, CRS_PROJETE, always_xy=True).transform
    point_proj = transform(project, point_geo)
    pk_m = line.project(point_proj)
    distance_axe_m = point_proj.distance(line)
    return pk_m / 1000.0, distance_axe_m


def compute_pk_for_rows(rows, line):
    results = []
    for r in rows:
        lat, lon = r.get("latitude"), r.get("longitude")
        if lat in (None, "") or lon in (None, ""):
            results.append({**r, "pk_calcule_km": None, "distance_axe_m": None,
                             "pk_fiable": False})
            continue
        try:
            point_geo = Point(float(lon), float(lat))
            pk_km, dist_m = project_point_on_line(line, point_geo)
            fiable = dist_m <= DISTANCE_MAX_PLAUSIBLE_M
            results.append({**r, "pk_calcule_km": round(pk_km, 3),
                             "distance_axe_m": round(dist_m, 1), "pk_fiable": fiable})
        except Exception as e:
            results.append({**r, "pk_calcule_km": None, "distance_axe_m": None,
                             "pk_fiable": False, "erreur": str(e)})
    return results


def main():
    ligne_path = find_first_existing(LIGNE_RN17_PATTERNS)
    villages_path = find_first_existing(VILLAGES_PATTERNS)

    if not ligne_path:
        print(f"⚠ Aucun fichier de tracé RN17 trouvé dans {GIS_DIR}/ "
              f"(attendu : RN17_lineaire.geojson/.shp/.kml/.gpx). Rien à calculer.")
        return

    print(f"Chargement du tracé RN17 depuis {ligne_path.name}...")
    line = load_line(ligne_path)
    print(f"  Longueur totale du tracé : {line.length/1000:.2f} km")

    # Les villages sont chargés en premier : ils servent à la fois à orienter
    # le PK (Ebolowa = PK 0) et au calcul du PK par village plus bas.
    villages_gdf = None
    if villages_path:
        print(f"\nChargement des villages depuis {villages_path.name}...")
        villages_gdf = load_points(villages_path)

    line = orienter_ligne(line, villages_gdf)

    # --- PK des PAP (à partir des exports déjà produits par le pipeline) ---
    pap_rows = []
    for csv_name in ("eak_par_principal.csv", "legacy_principal.csv"):
        p = DATA_DIR / csv_name
        if p.exists():
            with open(p, newline="", encoding="utf-8") as f:
                pap_rows.extend(list(csv.DictReader(f)))

    if pap_rows:
        results = compute_pk_for_rows(pap_rows, line)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(OUT_PK_PAP, "w", newline="", encoding="utf-8") as f:
            keys = list(results[0].keys())
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(results)
        n_calcules = sum(1 for r in results if r["pk_calcule_km"] is not None)
        n_fiables = sum(1 for r in results if r.get("pk_fiable"))
        print(f"\n  ✓ {OUT_PK_PAP.name} : PK calculé pour {n_calcules}/{len(results)} PAP "
              f"({n_fiables} jugé(s) fiable(s), < {DISTANCE_MAX_PLAUSIBLE_M} m de l'axe)")
        pk_valides = [r["pk_calcule_km"] for r in results if r.get("pk_fiable")]
        if pk_valides:
            print(f"  Kilométrage couvert (calculé) : PK {min(pk_valides):.2f} → "
                  f"{max(pk_valides):.2f} km (étendue {max(pk_valides)-min(pk_valides):.2f} km)")
    else:
        print("\n  (aucune donnée PAP trouvée — lancez d'abord kobo_sync.py / legacy_import.py)")

    # --- PK des villages : on ne retient QUE ceux dont le nom correspond à
    # l'un des 58 villages officiels des deux décrets (aucune condition de
    # distance au tracé — un village des décrets est retenu quelle que soit
    # sa distance à l'axe) ---
    if villages_gdf is not None:
        village_results = []
        villages_decrets_trouves = set()
        for _, row in villages_gdf.iterrows():
            nom_brut = row.get("nom", "?")
            nom_decret = correspond_a_un_village_decret(nom_brut)
            if nom_decret is None:
                continue
            pk_m = line.project(row.geometry)
            dist_m = row.geometry.distance(line)
            villages_decrets_trouves.add(nom_decret)
            village_results.append({
                "nom": nom_brut,
                "nom_decret_correspondant": nom_decret,
                "pk_calcule_km": round(pk_m / 1000.0, 3),
                "distance_axe_m": round(dist_m, 1),
            })
        village_results.sort(key=lambda r: r["pk_calcule_km"])
        with open(OUT_PK_VILLAGES, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["nom", "nom_decret_correspondant",
                                                     "pk_calcule_km", "distance_axe_m"])
            writer.writeheader()
            writer.writerows(village_results)
        print(f"\n  ✓ {OUT_PK_VILLAGES.name} : {len(village_results)} village(s) retenu(s) "
              f"(figurant dans les 2 décrets — sur {len(villages_gdf)} village(s) dans le "
              f"fichier source, sans condition de distance au tracé)")
        print(f"  Aperçu, trié par PK croissant :")
        for v in village_results[:20]:
            print(f"    PK {v['pk_calcule_km']:>7.2f} km — {v['nom']} "
                  f"(= {v['nom_decret_correspondant']}, à {v['distance_axe_m']:.0f} m du tracé)")

        # Signalement des correspondances géographiquement peu plausibles :
        # sans condition de distance, un nom peut matcher un homonyme éloigné
        # (village différent portant un nom proche) plutôt que le véritable
        # village du décret — utile pour un contrôle qualité ciblé.
        SEUIL_ALERTE_DISTANCE_M = 10000
        douteux = [v for v in village_results if v["distance_axe_m"] > SEUIL_ALERTE_DISTANCE_M]
        if douteux:
            print(f"\n  🔴 ATTENTION — {len(douteux)} correspondance(s) à plus de "
                  f"{SEUIL_ALERTE_DISTANCE_M/1000:.0f} km du tracé : probablement des homonymes "
                  f"(village différent portant un nom proche), pas le véritable village du "
                  f"corridor. À vérifier manuellement avant usage :")
            for v in sorted(douteux, key=lambda r: -r["distance_axe_m"]):
                print(f"    - {v['nom']} (= {v['nom_decret_correspondant']}) — "
                      f"{v['distance_axe_m']/1000:.1f} km du tracé")

        villages_manquants = sorted(set(VILLAGES_DECRETS) - villages_decrets_trouves)
        if villages_manquants:
            print(f"\n  ⚠ {len(villages_manquants)} village(s) des décrets NON localisé(s) dans "
                  f"le fichier Villages.zip (absents du fichier, ou orthographe trop différente "
                  f"pour la correspondance floue) :")
            for v in villages_manquants:
                print(f"    - {v}")
    else:
        print(f"\n(aucun fichier de villages trouvé dans {GIS_DIR}/ — étape ignorée)")


if __name__ == "__main__":
    main()
