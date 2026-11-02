#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
upload_media_ftp.py — Envoi TOLÉRANT des photos/signatures (site/media/) vers l'hébergeur.

Pourquoi : l'action FTP-Deploy s'arrêtait net (erreur 553 « Permission denied »)
sur UN fichier média verrouillé côté InfinityFree, ce qui faisait échouer toute la
synchronisation (e-mails d'échec quotidiens) et empêchait d'enregistrer l'état
d'avancement, donc la file d'attente grossissait chaque jour.

Principe :
  - une photo d'une fiche ne change jamais : on n'envoie QUE les fichiers absents
    du serveur (jamais de remplacement) ;
  - la liste des fichiers déjà envoyés est tenue dans media/.media-envoyes.json sur le
    serveur ; à la première exécution elle est amorcée depuis l'ancien état de
    FTP-Deploy (.ftp-deploy-sync-state.json) ;
  - un fichier refusé est consigné (avertissement) puis on continue ; le script ne
    fait jamais échouer le workflow à cause d'un média.
Variables : FTP_SERVER, FTP_USERNAME, FTP_PASSWORD, FTP_SERVER_DIR (défaut ./eakpar.fwh.is/htdocs/)
"""
import ftplib, io, json, os, sys, time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOCAL = BASE / "site" / "media"
SERVER = os.environ.get("FTP_SERVER", "")
USER = os.environ.get("FTP_USERNAME", "")
PWD = os.environ.get("FTP_PASSWORD", "")
SERVER_DIR = os.environ.get("FTP_SERVER_DIR", "./eakpar.fwh.is/htdocs/")
LISTE = ".media-envoyes.json"
ANCIEN_ETAT = ".ftp-deploy-sync-state.json"
BUDGET_S = int(os.environ.get("MEDIA_BUDGET_SECONDS", "1500"))   # 25 min max
EXCLUS = ("legacy/",)


def log(m):
    print(m, flush=True)


def connecter():
    ftp = ftplib.FTP(SERVER, timeout=60)
    ftp.login(USER, PWD)
    ftp.cwd(SERVER_DIR)
    return ftp


def lire(ftp, chemin):
    buf = io.BytesIO()
    try:
        ftp.retrbinary(f"RETR {chemin}", buf.write)
        return buf.getvalue()
    except ftplib.all_errors:
        return None


def main():
    if not (SERVER and USER and PWD):
        log("::warning::Identifiants FTP absents : envoi des médias ignoré.")
        return
    if not LOCAL.exists():
        log("Aucun dossier média local.")
        return
    t0 = time.time()
    ftp = connecter()

    brut = lire(ftp, "media/" + LISTE)
    if brut:
        envoyes = set(json.loads(brut.decode("utf-8")))
        log(f"Liste des médias déjà envoyés : {len(envoyes)}")
    else:
        envoyes = set()
        ancien = lire(ftp, ANCIEN_ETAT)
        if ancien:
            try:
                for e in json.loads(ancien.decode("utf-8")).get("data", []):
                    if e.get("type") == "file" and str(e.get("name", "")).startswith("media/"):
                        envoyes.add(e["name"])
            except Exception as ex:
                log(f"::warning::Ancien état FTP illisible : {ex}")
        log(f"Amorçage depuis l'ancien état FTP-Deploy : {len(envoyes)} médias connus")

    locaux = sorted(str(p.relative_to(BASE / "site")).replace(os.sep, "/") for p in LOCAL.rglob("*") if p.is_file())
    a_envoyer = [f for f in locaux if f not in envoyes and not any(f.startswith("media/" + x) for x in EXCLUS)]
    log(f"{len(locaux)} médias locaux, {len(a_envoyer)} à envoyer.")

    ok, refuses, dossiers = 0, [], set()
    for f in a_envoyer:
        if time.time() - t0 > BUDGET_S:
            log(f"::warning::Budget de temps atteint : {len(a_envoyer) - ok - len(refuses)} fichier(s) reportés à demain.")
            break
        dossier = f.rsplit("/", 1)[0]
        try:
            if dossier not in dossiers:
                for niveau in range(1, dossier.count("/") + 2):
                    try:
                        ftp.mkd("/".join(dossier.split("/")[:niveau]))
                    except ftplib.error_perm:
                        pass  # existe déjà
                dossiers.add(dossier)
            with open(BASE / "site" / f, "rb") as fh:
                ftp.storbinary(f"STOR {f}", fh)
            envoyes.add(f)
            ok += 1
        except ftplib.error_perm as e:        # 553 : fichier verrouillé côté hébergeur
            refuses.append((f, str(e)))
        except (ftplib.all_errors, OSError) as e:   # coupure réseau : on se reconnecte une fois
            try:
                ftp = connecter()
                dossiers.clear()
            except ftplib.all_errors:
                log(f"::warning::Connexion FTP perdue ({e}) : reste reporté à demain.")
                break
            refuses.append((f, str(e)))

    try:
        ftp.storbinary("STOR media/" + LISTE, io.BytesIO(json.dumps(sorted(envoyes)).encode("utf-8")))
    except ftplib.all_errors as e:
        log(f"::warning::Liste des médias envoyés non enregistrée : {e}")
    try:
        ftp.quit()
    except ftplib.all_errors:
        pass

    log(f"Médias envoyés : {ok} | refusés par l'hébergeur : {len(refuses)} | durée {int(time.time() - t0)} s")
    for f, e in refuses[:20]:
        log(f"::warning::Média refusé (verrouillé côté hébergeur ?) : {f} — {e}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # un média ne doit jamais faire échouer la synchronisation
        log(f"::warning::Envoi des médias interrompu : {e}")
