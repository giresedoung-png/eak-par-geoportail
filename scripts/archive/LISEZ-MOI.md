# Archive du Géoportail EAK-PAR (gel au 27/10/2026)

Les fiches recensées jusqu au 27/10/2026 (inclus) ont été supprimées de KoboToolbox
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

## Mise à jour du 02/11/2026
- Archive refondue sans doublon : l'identité d'une fiche est son `meta/rootUuid` (stable quand
  une fiche est modifiée dans Kobo), avec `_uuid` et `deprecatedID` en recoupement.
- Reconstitution depuis le Dashboard (Data_PAP, jamais purgé) : voir `rebuild_archive_27102026.py`.
- `doublons_probables.csv` : doublons de saisie quasi certains ; l'ancienne saisie est dans `exclusions.txt`.

## Reconstruction du 02/11/2026 (à partir des exports Kobo réels)
`scripts/rebuild_archive_depuis_exports.py` a recomposé l'archive depuis les exports Kobo du 12/10 et du 28/10/2026
(+ ancienne archive, Dashboard, checkpoint), une fiche = une identité (_uuid / rootUuid / deprecatedID), sans doublon.
Les tables de groupes répétables (décret, tombes, arbres, handicap, activités, terrain) sont reprises des onglets rep_*.
Les fiches saisies après le 28/10 arrivent par la synchronisation en direct (la version Kobo prime, sans double comptage).
