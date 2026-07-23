#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de kobo_sync.py (version InfinityFree/GitHub Actions) avec données simulées."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import kobo_sync as ks

MOCK_SUBMISSIONS = [
    {
        "_uuid": "uuid-001", "_id": 101, "_submission_time": "2026-07-20T08:00:00",
        "type_fiche": "nouveau",
        "A_identification_generale/troncon": "nord_mvila",
        "A_identification_generale/village": "vlg_adoum",
        "A_identification_generale/gps_localisation": "2.9000 11.1500 650 4.5",
        "C_identification_nouveau/C2_chef_menage/nom_prenom_cm": "Test Personne A",
        "C_identification_nouveau/C_annexe1_photos/photo_4_pap_visage": "photo_visage.jpg",
        "_attachments": [
            {"filename": "test/photo_visage.jpg", "download_url": "FAKE"}
        ],
    },
]

# On simule le téléchargement réseau (pas d'accès internet dans ce test)
def fake_download(submission, field_path, attachments_index, dest_dir):
    if submission.get(field_path):
        dest_dir.mkdir(parents=True, exist_ok=True)
        fake_path = dest_dir / (field_path.replace("/", "__") + ".jpg")
        fake_path.write_bytes(b"contenu_image_simule")
        return str(fake_path.relative_to(ks.SITE_DIR))
    return None

ks.download_attachment = fake_download

main_rows, repeat_rows, manifest_rows = ks.process_submissions(MOCK_SUBMISSIONS)
print("main_rows:", main_rows)
print("manifest_rows:", manifest_rows)

ks.DATA_DIR.mkdir(parents=True, exist_ok=True)
ks.export_csv(main_rows, ks.DATA_DIR / "test_principal.csv")
ks.export_geojson(main_rows, ks.DATA_DIR / "test_principal.geojson")
ks.export_gpx(main_rows, ks.DATA_DIR / "test_principal.gpx")

print("\nSITE_DIR =", ks.SITE_DIR)
print("Contenu généré :")
for p in sorted(ks.SITE_DIR.rglob("*")):
    if p.is_file():
        print(" -", p.relative_to(ks.SITE_DIR))

print("\nTEST TERMINÉ SANS ERREUR")
