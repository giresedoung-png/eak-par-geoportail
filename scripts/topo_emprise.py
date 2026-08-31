#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
topo_emprise.py — Corridor RN17 précis à partir du levé topographique réel
=============================================================================

Remplace/complète le tracé RN17 approximatif (extrait OSM) par les points
d'implantation d'emprise réels fournis par l'équipe Topographie :
  - Un point "D" (droite) et un point "G" (gauche) tous les ~20 m le long
    de la route, marquant les limites d'emprise implantées sur le terrain.
  - PK 0 = Ebolowa (confirmé par l'équipe topo).
  - Coordonnées fournies en UTM32N (colonnes nommées "LATITUDE"/"LONGITUDE"
    dans le fichier source, mais contenant en réalité des coordonnées
    projetées UTM32N Easting/Northing — vérifié empiriquement par
    recoupement avec la géographie connue du corridor).

Ce module fournit :
  - Le centre de chaussée reconstruit (moyenne des points D et G à chaque PK)
  - Pour tout point GPS (WGS84), sa position exacte le long du corridor
    (PK réel, pas une simple distance cumulée) et sa distance perpendiculaire
    au centre de la route — utilisées pour (a) le calcul du kilométrage,
    et (b) le classement dans les bandes de l'emprise (chaussée / trottoir /
    rigole / zone tampon / hors emprise).

Caractéristiques de la route (fournies) — demi-largeurs depuis l'axe :
  0,0 →  3,5 m : chaussée
  3,5 →  5,0 m : trottoir
  5,0 →  6,5 m : rigole
  6,5 → 11,5 m : zone tampon
  > 11,5 m     : hors emprise
  (emprise totale = 23 m, symétrique de part et d'autre de l'axe)
"""
import re
import math
from pathlib import Path

import openpyxl
from pyproj import Transformer

CRS_UTM = "EPSG:32632"
CRS_GEO = "EPSG:4326"

# Bandes de l'emprise (demi-largeur en mètres depuis l'axe reconstruit)
BANDE_CHAUSSEE_M = 3.5
BANDE_TROTTOIR_M = 5.0
BANDE_RIGOLE_M = 6.5
BANDE_ZONE_TAMPON_M = 11.5  # limite externe de l'emprise

_to_geo = Transformer.from_crs(CRS_UTM, CRS_GEO, always_xy=True)
_to_utm = Transformer.from_crs(CRS_GEO, CRS_UTM, always_xy=True)


def charger_points_topo(chemin_xlsx):
    """Lit le fichier topographique et retourne un dict {pk_metres: {"D":(E,N,alt), "G":(E,N,alt)}}."""
    wb = openpyxl.load_workbook(chemin_xlsx, data_only=True)
    ws = wb.active
    points = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        m = re.match(r"([DG])\.(\d+)", str(row[0]).strip())
        if not m:
            continue
        cote, pk = m.group(1), int(m.group(2))
        try:
            easting, northing, alt = float(row[1]), float(row[2]), float(row[3])
        except (TypeError, ValueError):
            continue
        points.setdefault(pk, {})[cote] = (easting, northing, alt)
    return points


def construire_axe(points):
    """Reconstruit l'axe de la route (liste ordonnée de (pk, easting, northing, alt))
    en moyennant les points D et G à chaque PK ; si un seul côté est disponible
    à un PK donné, on l'utilise tel quel plutôt que d'ignorer ce PK."""
    axe = []
    for pk in sorted(points.keys()):
        cotes = points[pk]
        if "D" in cotes and "G" in cotes:
            d, g = cotes["D"], cotes["G"]
            e = (d[0] + g[0]) / 2
            n = (d[1] + g[1]) / 2
            alt = (d[2] + g[2]) / 2
        else:
            e, n, alt = next(iter(cotes.values()))
        axe.append((pk, e, n, alt))
    return axe


class CorridorTopographique:
    """Représente le corridor RN17 reconstruit à partir du levé réel, et
    fournit la projection d'un point GPS quelconque sur ce corridor."""

    def __init__(self, chemin_xlsx):
        points = charger_points_topo(chemin_xlsx)
        self.axe = construire_axe(points)
        if not self.axe:
            raise ValueError("Aucun point exploitable dans le fichier topographique.")
        self.pk_min = self.axe[0][0] / 1000.0
        self.pk_max = self.axe[-1][0] / 1000.0

    def projeter(self, lat, lon):
        """Projette un point GPS (WGS84) sur l'axe reconstruit. Retourne un
        dict avec le PK réel (km), la distance perpendiculaire à l'axe (m),
        et la bande de l'emprise correspondante. Retourne None si le point
        est très éloigné de toute portion connue de l'axe (> 2 km), signe
        qu'il est hors de la zone couverte par ce levé topographique."""
        x0, y0 = _to_utm.transform(lon, lat)

        meilleure_distance = None
        meilleur_resultat = None
        for i in range(len(self.axe) - 1):
            pk1, e1, n1, _ = self.axe[i]
            pk2, e2, n2, _ = self.axe[i + 1]
            dx, dy = e2 - e1, n2 - n1
            longueur_segment = math.hypot(dx, dy)
            if longueur_segment == 0:
                continue
            # Projection du point sur le segment [i, i+1], t dans [0,1]
            t = ((x0 - e1) * dx + (y0 - n1) * dy) / (longueur_segment ** 2)
            t = max(0.0, min(1.0, t))
            ex, ey = e1 + t * dx, n1 + t * dy
            dist = math.hypot(x0 - ex, y0 - ey)
            if meilleure_distance is None or dist < meilleure_distance:
                meilleure_distance = dist
                pk_interpole = pk1 + t * (pk2 - pk1)
                meilleur_resultat = (pk_interpole, dist)

        if meilleur_resultat is None or meilleure_distance > 2000:
            return None

        pk_m, distance_m = meilleur_resultat
        return {
            "pk_km": round(pk_m / 1000.0, 4),
            "distance_axe_m": round(distance_m, 2),
            "bande_emprise": self._classer_bande(distance_m),
        }

    @staticmethod
    def _classer_bande(distance_m):
        if distance_m <= BANDE_CHAUSSEE_M:
            return "chaussee"
        if distance_m <= BANDE_TROTTOIR_M:
            return "trottoir"
        if distance_m <= BANDE_RIGOLE_M:
            return "rigole"
        if distance_m <= BANDE_ZONE_TAMPON_M:
            return "zone_tampon"
        return "hors_emprise"
