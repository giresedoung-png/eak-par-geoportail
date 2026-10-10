#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_snapshot_30092026.py — OUTIL À USAGE UNIQUE (reconstitution).

Reconstitue l'état du Géoportail EAK-PAR au 30/09/2026, avant la suppression
des fiches côté KoboToolbox (saturation du stockage), à partir de :
  1. l'onglet Data_PAP du Dashboard (export .xlsx), ajouté au fil des
     synchronisations : les N premières lignes « Kobo » (ordre d'ajout)
     correspondent aux soumissions synchronisées jusqu'au lot du 30/09/2026 ;
  2. l'export Kobo .xlsx de fin septembre (plus riche : _id, altitude,
     précision GPS, groupes répétables) ;
  3. scripts/last_sync.json (liste des _uuid déjà vus par le Géoportail) :
     les _uuid sans aucun détail récupérable sont conservés comme lignes
     « stub » pour que le décompte ne baisse pas.

Sortie : scripts/archive/archive_principal.csv (+ archive_<groupe>.csv).
Usage :
  python3 scripts/build_snapshot_30092026.py DASHBOARD.xlsx EXPORT_KOBO.xlsx N_LIGNES_KOBO [DATE_COUPURE=2026-10-01]
Date de gel retenue : 1er octobre 2026 (inclus). Sont figées : les N premières
lignes Kobo du Dashboard + toute ligne ultérieure dont Date_Enquete <= DATE_COUPURE.
"""
import csv, json, re, sys, unicodedata
from pathlib import Path
import openpyxl

BASE = Path(__file__).resolve().parent
ARCH = BASE / "archive"
ARCH.mkdir(exist_ok=True)
FIELDS = ["_uuid", "_id", "_submission_time", "type_fiche", "troncon", "departement",
          "arrondissement", "village", "date_enquete", "pk", "nom_prenom_cm",
          "latitude", "longitude", "altitude", "precision_gps", "_origine"]
REPEATS = {"rep_pap_decret": "pap_decret", "rep_handicap": "handicap",
           "rep_activite_conjoint": "activite_conjoint", "rep_activite_enfant": "activite_enfant",
           "rep_activite_autre_membre": "activite_autre_membre", "rep_terrain": "terrain",
           "rep_tombes": "tombes", "rep_arbres_concession": "arbres_concession"}


def slug(s):
    s = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def iso(d):
    return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else (str(d)[:10] if d else "")


def num(v):
    try:
        return float(v) if v not in (None, "") else ""
    except (TypeError, ValueError):
        return ""


def main(dash, kobo, n_kobo, coupure="2026-10-01"):
    n_kobo = int(n_kobo)
    wb = openpyxl.load_workbook(dash, read_only=True, data_only=True)
    dp = [r for r in list(wb["Data_PAP"].iter_rows(values_only=True))[1:] if r and r[0]]
    tous_kobo = [r for r in dp if str(r[1]) == "Kobo"]
    dp_kobo = tous_kobo[:n_kobo] + [r for r in tous_kobo[n_kobo:] if iso(r[8]) and iso(r[8]) <= coupure]

    wk = openpyxl.load_workbook(kobo, read_only=True, data_only=True)
    ws = wk[wk.sheetnames[0]]
    it = ws.iter_rows(values_only=True)
    head = list(next(it))
    ix = {h: i for i, h in enumerate(head) if h}
    g = lambda r, k: r[ix[k]] if k in ix and ix[k] < len(r) else None
    rich = {}
    for r in it:
        u = g(r, "_uuid")
        if not u:
            continue
        lat, lon = num(g(r, "_gps_localisation_latitude")), num(g(r, "_gps_localisation_longitude"))
        sub = g(r, "_submission_time")
        nom = (g(r, "nom_prenom_cm") or g(r, "nom_repondant") or "")
        rich[u] = {
            "_uuid": u, "_id": g(r, "_id"), "_submission_time": iso(sub) if sub else "",
            "type_fiche": g(r, "type_fiche") or "", "troncon": g(r, "troncon") or "",
            "departement": g(r, "departement") or "", "arrondissement": g(r, "arrondissement") or "",
            "village": g(r, "village") or "", "date_enquete": iso(g(r, "date_enquete")),
            "pk": g(r, "pk") or "", "nom_prenom_cm": nom, "latitude": lat, "longitude": lon,
            "altitude": num(g(r, "_gps_localisation_altitude")),
            "precision_gps": num(g(r, "_gps_localisation_precision")), "_origine": "gel_01102026",
        }

    # correspondance libellé Dashboard -> code village Kobo (appris sur le recoupement)
    lab2code, cat2type = {}, {}
    for r in dp_kobo:
        if r[0] in rich:
            lab2code[slug(r[4])] = rich[r[0]]["village"]
            cat2type.setdefault(r[2], rich[r[0]]["type_fiche"])
    out = {}
    for u, row in rich.items():
        out[u] = row
    for r in dp_kobo:
        u = r[0]
        if u in out:
            continue
        lat, lon = num(r[13]), num(r[14])
        out[u] = {
            "_uuid": u, "_id": "", "_submission_time": "",
            "type_fiche": cat2type.get(r[2]) or ("decret" if "decret" in slug(r[2]) else "nouveau"),
            "troncon": r[7] or "", "departement": r[6] or "", "arrondissement": r[5] or "",
            "village": lab2code.get(slug(r[4]), "vlg_" + slug(r[4])),
            "date_enquete": iso(r[8]), "pk": r[9] or "", "nom_prenom_cm": r[3] or "",
            "latitude": lat, "longitude": lon, "altitude": "", "precision_gps": "",
            "_origine": "gel_01102026_dashboard",
        }
    # _uuid vus par le Géoportail mais sans aucun détail récupérable
    cp = json.loads((BASE / "last_sync.json").read_text(encoding="utf-8"))
    stubs = [u for u in cp.get("synced_uuids", []) if u and u not in out
             and u not in {r[0] for r in dp}]  # (hors lignes postérieures au 30/09 déjà dans Data_PAP)
    for u in stubs:
        out[u] = {k: "" for k in FIELDS}
        out[u].update({"_uuid": u, "type_fiche": "inconnu", "_origine": "stub_checkpoint_sans_detail"})

    with open(ARCH / "archive_principal.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out.values())

    # groupes répétables (disponibles uniquement via l'export Kobo)
    for sheet, key in REPEATS.items():
        if sheet not in wk.sheetnames:
            continue
        rows = list(wk[sheet].iter_rows(values_only=True))
        h = list(rows[0])
        iu = h.index("_submission__uuid")
        cols = [c for c in h if c and not str(c).startswith("_")]
        recs = []
        for k, r in enumerate(rows[1:]):
            if r[iu] in out:
                d = {"_uuid": r[iu], "_id": r[h.index("_submission__id")], "_index_repeat": r[h.index("_index")]}
                d.update({c: r[h.index(c)] for c in cols})
                recs.append(d)
        if recs:
            keys = list(recs[0].keys())
            with open(ARCH / f"archive_{key}.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=keys)
                w.writeheader()
                w.writerows(recs)
    n_stub = sum(1 for v in out.values() if v["_origine"].startswith("stub"))
    print(f"Archive reconstituée : {len(out)} fiches ({n_stub} stubs sans détail).")


if __name__ == "__main__":
    if len(sys.argv) not in (4, 5):
        sys.exit(__doc__)
    main(*sys.argv[1:])
