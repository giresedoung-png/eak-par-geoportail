#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rebuild_archive_depuis_exports.py — OUTIL À USAGE UNIQUE.

Reconstitue l'archive du Géoportail pour qu'il reflète la RÉALITÉ du terrain :
fiches supprimées de Kobo (12/10 et 28/10/2026) + fiches qui y demeurent.
(Les fiches ajoutées depuis arrivent par la synchronisation en direct, qui prime
sur l'archive pour une même fiche.)

Sources, par priorité décroissante (pour chaque champ, la 1re valeur non vide gagne) :
  1. export Kobo du 28/10/2026   2. export Kobo du 12/10/2026
  3. archive existante           4. Dashboard (Data_PAP)  5. last_sync.json (stubs)

Une fiche = une IDENTITÉ {_uuid, meta/rootUuid, _deprecated_uuid} : une fiche modifiée
dans Kobo change d'_uuid mais garde sa racine -> elle n'est comptée qu'une fois.
Les tables de groupes répétables sont reprises des onglets rep_* des exports.

Usage : python3 -I scripts/rebuild_archive_depuis_exports.py EXPORT_28_10.xlsx EXPORT_12_10.xlsx [DASHBOARD.xlsx]
"""
import csv, json, sys
from pathlib import Path
import openpyxl

BASE = Path(__file__).resolve().parent
ARCH = BASE / "archive"
FIELDS = ["_uuid", "_root_uuid", "_deprecated_uuid", "_id", "_submission_time", "type_fiche",
          "troncon", "departement", "arrondissement", "village", "date_enquete", "pk",
          "nom_prenom_cm", "latitude", "longitude", "altitude", "precision_gps", "_origine"]
SHEETS = {"pap_decret": "rep_pap_decret", "handicap": "rep_handicap", "activite_conjoint": "rep_activite_conjoint",
          "activite_enfant": "rep_activite_enfant", "activite_autre_membre": "rep_activite_autre_membre",
          "terrain": "rep_terrain", "tombes": "rep_tombes", "arbres_concession": "rep_arbres_concession"}


def nu(v):
    s = str(v or "").strip()
    return s[5:] if s.startswith("uuid:") else s


def iso(d):
    return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else (str(d)[:10] if d else "")


def clean(v):
    if v is None:
        return ""
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    return v


def lire_export(path, etiquette):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    it = wb[wb.sheetnames[0]].iter_rows(values_only=True)
    h = list(next(it))
    ix = {c: i for i, c in enumerate(h) if c}
    g = lambda x, c: x[ix[c]] if c in ix else None
    fiches, reps = [], {}
    for x in it:
        if not g(x, "_uuid"):
            continue
        u = nu(g(x, "_uuid"))
        fiches.append({
            "_uuid": u, "_root_uuid": nu(g(x, "meta/rootUuid")), "_deprecated_uuid": nu(g(x, "meta/deprecatedID")),
            "_id": g(x, "_id") or "", "_submission_time": iso(g(x, "_submission_time")),
            "type_fiche": g(x, "type_fiche") or "", "troncon": g(x, "troncon") or "",
            "departement": g(x, "departement") or "", "arrondissement": g(x, "arrondissement") or "",
            "village": g(x, "village") or "", "date_enquete": iso(g(x, "date_enquete")), "pk": g(x, "pk") or "",
            "nom_prenom_cm": g(x, "nom_prenom_cm") or "",
            "latitude": g(x, "_gps_localisation_latitude") or "", "longitude": g(x, "_gps_localisation_longitude") or "",
            "altitude": g(x, "_gps_localisation_altitude") or "", "precision_gps": g(x, "_gps_localisation_precision") or "",
            "_origine": etiquette})
    for cle, feuille in SHEETS.items():
        if feuille not in wb.sheetnames:
            continue
        it2 = wb[feuille].iter_rows(values_only=True)
        h2 = list(next(it2))
        ju = h2.index("_submission__uuid")
        jid = h2.index("_submission__id")
        jx = h2.index("_index")
        champs = [c for c in h2 if c and not c.startswith("_")]
        for y in it2:
            if not y[ju]:
                continue
            d = {"_uuid": nu(y[ju]), "_id": y[jid], "_index_repeat": (y[jx] or 1) - 1}
            for c in champs:
                d[c] = clean(y[h2.index(c)])
            reps.setdefault(cle, []).append(d)
        # nom manuel / code PAP pour le module décret
    return fiches, reps


def lire_csv(p):
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main(e28, e12, dash=None):
    f28, r28 = lire_export(e28, "export_28102026")
    f12, r12 = lire_export(e12, "export_12102026")
    ancien = [dict({k: "" for k in FIELDS}, **r) for r in lire_csv(ARCH / "archive_principal.csv")]
    sources = [("e28", f28), ("e12", f12), ("arch", ancien)]

    # Dashboard
    dp = []
    if dash:
        wb = openpyxl.load_workbook(dash, read_only=True, data_only=True)
        lab2code = {}
        for r in list(wb["Data_PAP"].iter_rows(values_only=True))[1:]:
            if r and r[0] and str(r[1]) == "Kobo":
                dp.append(r)
        from rebuild_archive_27102026 import norm, num  # même dossier
        par_u = {r["_uuid"]: r for r in ancien}
        for r in dp:
            a = par_u.get(str(r[0]).strip())
            if a and a["village"]:
                lab2code[norm(r[4])] = a["village"]
        cat2type = {}
        for r in dp:
            a = par_u.get(str(r[0]).strip())
            if a and a["type_fiche"]:
                cat2type.setdefault(r[2], a["type_fiche"])
        fd = []
        for r in dp:
            fd.append({k: "" for k in FIELDS} | {
                "_uuid": str(r[0]).strip(), "type_fiche": cat2type.get(r[2]) or ("decret" if "decret" in norm(r[2]) else "nouveau"),
                "troncon": r[7] or "", "departement": r[6] or "", "arrondissement": r[5] or "",
                "village": lab2code.get(norm(r[4]), "vlg_" + norm(r[4]).replace(" ", "_")),
                "date_enquete": iso(r[8]), "pk": r[9] or "", "nom_prenom_cm": r[3] or "",
                "latitude": num(r[13]), "longitude": num(r[14]), "_origine": "dashboard"})
        sources.append(("dash", fd))
    cp = json.loads((BASE / "last_sync.json").read_text(encoding="utf-8"))
    sources.append(("stub", [{k: "" for k in FIELDS} | {"_uuid": u, "type_fiche": "inconnu", "_origine": "stub_checkpoint_sans_detail"}
                             for u in cp.get("synced_uuids", []) if u]))

    # --- union-find sur les identités
    items = [(nom, r) for nom, rows in sources for r in rows]
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    vu = {}
    for i, (_, r) in enumerate(items):
        for x in {r["_uuid"], r["_root_uuid"], r["_deprecated_uuid"]} - {""}:
            if x in vu:
                parent[find(i)] = find(vu[x])
            else:
                vu[x] = i
    classes = {}
    for i in range(len(items)):
        classes.setdefault(find(i), []).append(i)

    ordre = {"e28": 0, "e12": 1, "arch": 2, "dash": 3, "stub": 4}
    finales, stats, exclus_src = [], {}, {}
    for membres in classes.values():
        membres.sort(key=lambda i: ordre[items[i][0]])
        noms = {items[i][0] for i in membres}
        cle = "+".join(s for s in ("e12", "e28", "arch", "dash", "stub") if s in noms)
        stats[cle] = stats.get(cle, 0) + 1
        best = dict(items[membres[0]][1])
        for k in FIELDS:
            if k == "_origine":
                continue
            if best.get(k) in ("", None):
                for i in membres[1:]:
                    v = items[i][1].get(k)
                    if v not in ("", None):
                        best[k] = v
                        break
        # nom : les noms « code » de décret ne sont pas utiles ; garder celui d'archive/dashboard
        ids = set()
        for i in membres:
            ids |= {items[i][1]["_uuid"], items[i][1]["_root_uuid"], items[i][1]["_deprecated_uuid"]}
        ids -= {"", best["_uuid"]}
        if not best["_root_uuid"]:
            best["_root_uuid"] = next((items[i][1]["_root_uuid"] for i in membres if items[i][1]["_root_uuid"]), "")
        reste = sorted(ids - {best["_root_uuid"]})
        if reste and not best["_deprecated_uuid"]:
            best["_deprecated_uuid"] = reste[0]
        best["_origine"] = {"e28": "export_28102026", "e12": "export_12102026"}.get(items[membres[0]][0], items[membres[0]][1]["_origine"])
        best["_source_ids"] = ids | {best["_uuid"]}
        finales.append(best)

    # --- contrôle d'unicité strict
    deja = {}
    for r in finales:
        for x in {r["_uuid"], r["_root_uuid"], r["_deprecated_uuid"]} - {""}:
            assert x not in deja, f"identité en double {x}"
            deja[x] = r
    assert len({r["_uuid"] for r in finales}) == len(finales)

    # --- tables de groupes répétables
    uuid_final = {}
    for r in finales:
        for x in r["_source_ids"]:
            uuid_final[x] = r["_uuid"]
    rapport = {}
    for cle in SHEETS:
        existant = lire_csv(ARCH / f"archive_{cle}.csv")
        entete = list(existant[0].keys()) if existant else None
        retenu, couvert = [], set()
        for exp, reps, f in (("e28", r28, f28), ("e12", r12, f12)):
            presentes = {r["_uuid"] for r in f}
            for ligne in reps.get(cle, []):
                if ligne["_uuid"] not in presentes:
                    continue
                cible = uuid_final[ligne["_uuid"]]
                retenu.append((exp, cible, ligne))
        # une fiche n'est reprise que depuis UNE source d'export (la plus prioritaire qui la contient)
        source_fiche = {}
        for exp, cible, ligne in retenu:
            if cible not in source_fiche or exp == "e28" and source_fiche[cible] == "e12":
                source_fiche[cible] = exp
        sortie = [dict(l, _uuid=c) for e, c, l in retenu if source_fiche[c] == e]
        couvert = set(source_fiche)
        # lignes de l'ancienne archive pour les fiches absentes des exports
        for l in existant:
            c = uuid_final.get(l["_uuid"])
            if c and c not in couvert:
                sortie.append(dict(l, _uuid=c))
        champs = list(entete or [])
        for l in sortie:
            for k in l:
                if k not in champs:
                    champs.append(k)
        for k in ("_uuid", "_id", "_index_repeat"):
            if k not in champs:
                champs.insert(0, k)
        with open(ARCH / f"archive_{cle}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=champs, extrasaction="ignore", restval="")
            w.writeheader()
            w.writerows(sortie)
        rapport[cle] = len(sortie)

    finales.sort(key=lambda r: (str(r["date_enquete"]), str(r["_uuid"])))
    with open(ARCH / "archive_principal.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(finales)
    print(f"Archive : {len(finales)} fiches uniques.")
    for k, v in sorted(stats.items()):
        print(f"   {k:<22} {v}")
    print("Tables répétables :", rapport)
    t = {}
    for r in finales:
        t[r["type_fiche"]] = t.get(r["type_fiche"], 0) + 1
    print("Par type :", t)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(*sys.argv[1:4])
