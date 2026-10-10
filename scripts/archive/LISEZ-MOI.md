# Archive du Géoportail EAK-PAR (gel au 01/10/2026)

Les fiches recensées jusqu au 01/10/2026 (inclus) ont été supprimées de KoboToolbox
(saturation du stockage). `archive_*.csv` contient leur reconstitution ; elle est
fusionnée à chaque synchronisation avec les données Kobo en direct.

- Kobo en direct prime sur l'archive (même `_uuid`) : une fiche corrigée est mise à jour.
- Une fiche supprimée de Kobo reste sur le Géoportail (sauf si son `_uuid` est dans `exclusions.txt`).
- Toute nouvelle fiche vue par la synchronisation est ajoutée à l'archive ; le workflow
  la commit automatiquement (`git add scripts/archive`).
- `_origine` : `gel_01102026` (export Kobo, complet), `gel_01102026_dashboard`
  (reconstitué depuis Data_PAP du Dashboard), `stub_checkpoint_sans_detail`
  (13 fiches dont seul l'identifiant est connu : comptées, sans village/position),
  `kobo_direct`, `archive`.
- Désactiver l'archive : variable d'environnement `ARCHIVE_ACTIVE=false`.
- `build_gel_01102026.py` = outil à usage unique de reconstitution.
