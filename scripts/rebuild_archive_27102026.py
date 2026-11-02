#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rebuild_archive_27102026.py — OUTIL À USAGE UNIQUE (gel du Géoportail au 27/10/2026).

Reconstitue l'archive des fiches (scripts/archive/archive_principal.csv) en
SANS DOUBLON, à partir de :
  1. l'archive existante (gel du 01/10/2026) ;
  2. l'onglet Data_PAP du Dashboard (Apps Script) — ajouté au fil des
     synchronisations, il n'est jamais purgé : il conserve donc les fiches
     supprimées de Kobo (suppressions des 12/10 et 28/10/2026) ;
  3. l'export Kobo de fin septembre (pour renseigner l'identité stable
     meta/rootUuid des fiches qu'il contient) ;
  4. scripts/last_sync.json (identifiants déjà vus ; ceux sans aucun détail
     sont gardés comme lignes « stub »).

Usage :
  python3 scripts/rebuild_archive_27102026.py DASHBOARD.xlsx [EXPORT_KOBO.xlsx] [DATE_COUPURE=2026-10-27]
"""
import csv, json, math, re, sys, unicodedata
from pathlib import Path
import openpyxl

BASE = Path(__file__).resolve().parent
ARCH = BASE / "archive"
FIELDS = ["_uuid", "_root_uuid", "_deprecated_uuid", "_id", "_submission_time", "type_fiche",
          "troncon", "departement", "arrondissement", "village", "date_enquete", "pk",
          "nom_prenom_cm", "latitude", "longitude", "altitude", "precision_gps", "_origine"]


def norm(s):
    s = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def iso(d):
    return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else (str(d)[:10] if d else "")


def num(v):
    try:
        return float(v) if v not in (None, "") else ""
    except (TypeError, ValueError):
        return ""


def metres(a, b):
    if "" in (a["latitude"], a["longitude"], b["latitude"], b["longitude"]):
        return None
    dy = (a["latitude"] - b["latitude"]) * 111320.0
    dx = (a["longitude"] - b["longitude"]) * 111320.0 * math.cos(math.radians(a["latitude"]))
    return math.hypot(dx, dy)


def main(dash, kobo=None, coupure="2026-10-27"):
    # 1. archive existante
    with open(ARCH / "archive_principal.csv", newline="", encoding="utf-8") as f:
        rows = [dict({k: "" for k in FIELDS}, **r) for r in csv.DictReader(f)]
    for r in rows:
        for k in ("latitude", "longitude", "altitude", "precision_gps"):
            r[k] = num(r.get(k))

    # 3. identité stable depuis l'export Kobo de fin septembre
    if kobo:
        wk = openpyxl.load_workbook(kobo, read_only=True, data_only=True)
        it = wk[wk.sheetnames[0]].iter_rows(values_only=True)
        h = list(next(it))
        iu = h.index("_uuid")
        ir = next((i for i, c in enumerate(h) if c and "rootUuid" in str(c)), None)
        racine = {}
        for x in it:
            if x[iu] and ir is not None and x[ir]:
                racine[x[iu]] = str(x[ir]).replace("uuid:", "")
        for r in rows:
            if r["_uuid"] in racine:
                r["_root_uuid"] = racine[r["_uuid"]]

    # identités déjà présentes
    def ids(r):
        return {x for x in (r["_uuid"], r["_root_uuid"], r["_deprecated_uuid"]) if x}

    # Une fiche modifiée dans Kobo change de _uuid : l'ancienne archive peut donc la
    # contenir deux fois (version d'origine + version modifiée). On fusionne les lignes
    # qui partagent une identité en gardant la plus riche (export Kobo > Dashboard) et
    # on conserve les deux identifiants pour que Kobo en direct la reconnaisse.
    def richesse(r):
        return (1 if r["_id"] != "" else 0, 1 if not r["_origine"].startswith("stub") else 0,
                1 if r["_origine"].startswith("snapshot") or r["_origine"].startswith("gel_01102026") and r["_id"] != "" else 0)
    groupes_id, parent = {}, list(range(len(rows)))

    def trouver(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i, r in enumerate(rows):
        for x in ids(r):
            if x in groupes_id:
                parent[trouver(i)] = trouver(groupes_id[x])
            else:
                groupes_id[x] = i
    classes = {}
    for i in range(len(rows)):
        classes.setdefault(trouver(i), []).append(i)
    fusionnees, collapsed = [], 0
    for membres in classes.values():
        if len(membres) == 1:
            fusionnees.append(rows[membres[0]])
            continue
        collapsed += len(membres) - 1
        membres.sort(key=lambda i: richesse(rows[i]), reverse=True)
        garde = dict(rows[membres[0]])
        autres = set().union(*[ids(rows[i]) for i in membres]) - {garde["_uuid"]}
        if not garde["_root_uuid"]:
            garde["_root_uuid"] = next((rows[i]["_root_uuid"] for i in membres if rows[i]["_root_uuid"]), "")
        reste = sorted(autres - {garde["_root_uuid"]})
        if reste and not garde["_deprecated_uuid"]:
            garde["_deprecated_uuid"] = reste[0]
        fusionnees.append(garde)
    rows = fusionnees
    deja = {}
    for r in rows:
        for x in ids(r):
            deja[x] = r
    par_uuid_init = {r["_uuid"]: r for r in rows}

    # 2. Dashboard / Data_PAP
    wb = openpyxl.load_workbook(dash, read_only=True, data_only=True)
    dp = [r for r in list(wb["Data_PAP"].iter_rows(values_only=True))[1:]
          if r and r[0] and str(r[1]) == "Kobo"]
    lab2code, cat2type = {}, {}
    par_uuid = {r["_uuid"]: r for r in rows}
    for r in dp:
        a = par_uuid.get(r[0])
        if a and a["village"]:
            lab2code[norm(r[4])] = a["village"]
            cat2type.setdefault(r[2], a["type_fiche"])
    ajoutees, ignorees_date, doublons_uuid = 0, 0, 0
    for r in dp:
        u = str(r[0]).strip()
        if u in deja:
            if u in par_uuid or True:
                doublons_uuid += 1
            continue
        d = iso(r[8])
        if "2026-10-27" < d <= "2026-12-31" or (d and d > coupure and d[:4] == "2026"):
            ignorees_date += 1
            continue
        new = {k: "" for k in FIELDS}
        new.update({
            "_uuid": u,
            "type_fiche": cat2type.get(r[2]) or ("decret" if "decret" in norm(r[2]) else "nouveau"),
            "troncon": r[7] or "", "departement": r[6] or "", "arrondissement": r[5] or "",
            "village": lab2code.get(norm(r[4]), "vlg_" + norm(r[4]).replace(" ", "_")),
            "date_enquete": d, "pk": r[9] or "", "nom_prenom_cm": r[3] or "",
            "latitude": num(r[13]), "longitude": num(r[14]),
            "_origine": "gel_27102026_dashboard",
        })
        rows.append(new)
        deja[u] = new
        ajoutees += 1

    # 4. identifiants vus par le Géoportail mais sans aucun détail
    cp = json.loads((BASE / "last_sync.json").read_text(encoding="utf-8"))
    stubs = 0
    for u in cp.get("synced_uuids", []):
        if u and u not in deja:
            new = {k: "" for k in FIELDS}
            new.update({"_uuid": u, "type_fiche": "inconnu", "_origine": "stub_checkpoint_sans_detail"})
            rows.append(new)
            deja[u] = new
            stubs += 1

    # Contrôle d'unicité strict
    vus = {}
    for r in rows:
        for x in ids(r):
            assert x not in vus or vus[x] is r, f"identité en double : {x}"
            vus[x] = r
    assert len({r["_uuid"] for r in rows}) == len(rows)

    # Doublons probables (même nom + village + type)
    groupes = {}
    for r in rows:
        if r["nom_prenom_cm"]:
            groupes.setdefault((norm(r["nom_prenom_cm"]), norm(r["village"].replace("vlg_", "")), r["type_fiche"]), []).append(r)
    certains = []
    for g in groupes.values():
        if len(g) < 2:
            continue
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                a, b = g[i], g[j]
                dist = metres(a, b)
                if a["date_enquete"] == b["date_enquete"] and (dist is None or dist <= 30):
                    certains.append((a, b, dist))
    rapport = ARCH / "doublons_probables.csv"
    with open(rapport, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["nom", "village", "type", "date", "uuid_1", "uuid_2", "distance_m"])
        for a, b, d in certains:
            w.writerow([a["nom_prenom_cm"], a["village"], a["type_fiche"], a["date_enquete"], a["_uuid"], b["_uuid"],
                        "" if d is None else round(d, 1)])
    with open(ARCH / "archive_principal.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{collapsed} doublon(s) d'identité fusionné(s) dans l'ancienne archive (fiches modifiées dans Kobo).")
    print(f"Archive : {len(rows)} fiches uniques (+{ajoutees} depuis le Dashboard, +{stubs} stubs, "
          f"{ignorees_date} ignorées car postérieures au {coupure}, {doublons_uuid} déjà présentes).")
    print(f"Doublons quasi certains (même nom/village/type/date, ≤ 30 m) : {len(certains)} → {rapport.name}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(*sys.argv[1:])
