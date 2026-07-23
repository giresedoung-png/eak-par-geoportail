# Géoportail EAK-PAR — Architecture 100% gratuite
## Kobo → GitHub Actions → InfinityFree (FTP) → Leaflet

Ce dossier remplace l'architecture VPS/PostGIS/GeoServer par une chaîne
entièrement gratuite, adaptée à un usage de reporting interne/institutionnel
à trafic modéré.

## Comment ça fonctionne

```
Chaque jour à 18h00 UTC (~19-20h heure du Cameroun) :
  GitHub Actions se réveille automatiquement
    → exécute scripts/kobo_sync.py (récupère les nouvelles soumissions Kobo,
      télécharge et compresse les photos/signatures, génère GeoJSON/CSV/GPX)
    → envoie le contenu du dossier site/ vers votre hébergement InfinityFree
      via FTP
  → Le géoportail (site/index.html) est à jour, sans que vous n'ayez
    besoin d'y toucher.
```

## Structure du dossier

```
geoportail_free/
├── .github/workflows/sync_and_deploy.yml   # Le "chef d'orchestre" quotidien
├── scripts/
│   ├── kobo_sync.py           # Récupère + compresse + structure les données
│   └── test_with_mock_data.py # Test déjà validé (aucune connexion requise)
├── requirements.txt
├── site/                      # ⚠️ CE dossier est envoyé tel quel vers InfinityFree
│   ├── index.html             # La page carte (Leaflet)
│   ├── data/                  # (généré) GeoJSON, CSV, GPX
│   └── media/                 # (généré) photos/signatures compressées
└── README.md
```

## Mise en place — étape par étape

### 1. Créer un dépôt GitHub (gratuit)

- Créez un compte sur [github.com](https://github.com) si vous n'en avez pas
- Créez un nouveau dépôt (public ou privé, les deux fonctionnent) — ex. `eak-par-geoportail`
- Uploadez tout le contenu de ce dossier dans le dépôt (via l'interface web
  "Add file → Upload files", ou via `git push` si vous êtes à l'aise en ligne
  de commande)

### 2. Récupérer vos identifiants Kobo

- **Jeton API** : `kf.kobotoolbox.org` → cliquez sur votre nom (bas de
  l'écran) → *Account Settings* → onglet *Security* → section *API Key*
- **UID du formulaire** : visible dans l'URL de votre projet, ex.
  `https://kf.kobotoolbox.org/#/forms/aBcD1234efGH/` → l'UID est `aBcD1234efGH`

### 3. Récupérer vos identifiants FTP InfinityFree

Sur `dash.infinityfree.com` → votre compte d'hébergement → section
**FTP Details** : vous y trouverez l'adresse du serveur FTP, le nom
d'utilisateur et le mot de passe (ou vous pouvez en définir un nouveau).

### 4. Configurer les secrets sur GitHub

Dans votre dépôt GitHub : **Settings** → **Secrets and variables** →
**Actions** → **New repository secret**. Créez chacun des secrets suivants :

| Nom du secret | Valeur |
|---|---|
| `KOBO_SERVER` | `https://kf.kobotoolbox.org` (ou l'URL de votre serveur Kobo) |
| `KOBO_API_TOKEN` | Votre jeton API Kobo (étape 2) |
| `KOBO_ASSET_UID` | L'UID de votre formulaire (étape 2) |
| `FTP_SERVER` | L'adresse du serveur FTP InfinityFree (étape 3) |
| `FTP_USERNAME` | Votre identifiant FTP InfinityFree |
| `FTP_PASSWORD` | Votre mot de passe FTP InfinityFree |
| `SYNC_MEDIA` | `true` (ou `false` si vous voulez d'abord tester sans photos, pour économiser le quota) |

⚠️ Ces secrets sont chiffrés par GitHub et ne sont jamais visibles dans les
journaux d'exécution — ne les mettez en revanche jamais directement dans le
code ou dans un fichier normal du dépôt.

### 5. Lancer une première synchronisation manuelle

Dans votre dépôt GitHub : onglet **Actions** → sélectionnez le workflow
*"Synchronisation quotidienne EAK-PAR"* → bouton **Run workflow** → **Run
workflow** (vert). Suivez l'exécution en direct (quelques minutes). Si tout
est vert, votre géoportail est déjà en ligne sur votre sous-domaine
InfinityFree (ex. `https://votresite.infinityfreeapp.com`).

Ensuite, le workflow se relancera automatiquement chaque jour, sans rien
faire de plus.

### 6. Vérifier le résultat

Ouvrez l'URL de votre site InfinityFree : la carte doit afficher les points
collectés, avec info-bulle (nom, village, tronçon, photo si disponible).

## Gestion des quotas InfinityFree (important)

InfinityFree impose des limites (gratuit oblige) :
- **~30 000 fichiers (inodes)** au total sur le compte
- **~5 Go de stockage réel**
- **50 000 visites/24h**

Pour rester large en dessous de ces plafonds :
- Les photos sont **automatiquement compressées** (1280 px max, qualité 70%)
  par `kobo_sync.py` — une photo de 4-6 Mo devient quelques dizaines de Ko.
- Si le nombre de fichiers devient préoccupant (visible dans le tableau de
  bord InfinityFree, section *Statistics*), vous pouvez désactiver
  temporairement la synchronisation des médias en mettant le secret
  `SYNC_MEDIA` à `false` — seules les données géographiques/statistiques
  continueront à se mettre à jour, sans les photos.
- Vous pouvez aussi réduire `IMAGE_MAX_DIMENSION` (ex. `800` au lieu de
  `1280`) directement dans `.github/workflows/sync_and_deploy.yml` pour
  gagner encore en légèreté.

## Limites de cette architecture (à connaître)

- Pas de base de données spatiale (PostGIS) ni de flux OGC standard
  (WMS/WFS) — la carte lit directement un fichier GeoJSON, ce qui suffit
  pour de la consultation/du reporting, mais ne permet pas de requêtes
  spatiales complexes côté serveur.
- Fiabilité et disponibilité non garanties au niveau d'un hébergement payant
  — acceptable pour un usage interne/institutionnel, à reconsidérer si le
  géoportail devient une vitrine officielle à fort enjeu vis-à-vis de
  bailleurs.
- GitHub Actions gratuit a une limite mensuelle de minutes d'exécution
  (largement suffisante pour une synchronisation quotidienne de quelques
  minutes, mais à garder en tête si vous multipliez les automatisations).

## Évolution future

Si le projet grandit (plus de trafic, besoin de requêtes spatiales
avancées, exigence de disponibilité plus forte), la même logique de script
(`kobo_sync.py`) reste réutilisable : il suffira de remplacer l'étape
d'envoi FTP par un chargement dans PostGIS et de migrer vers un VPS avec
GeoServer, sans repartir de zéro.

## Intégration des données papier historiques (pré-Kobo)

Une partie des PAP a été enquêtée avant la mise en service du formulaire
Kobo, sur questionnaire papier, dépouillée dans un masque de saisie Excel,
avec des photos prises séparément via **NoteCam**.

### Comment ça s'intègre au pipeline

```
scripts/legacy_import.py   → lit vos masques Excel + photos NoteCam
                              (coordonnées GPS extraites automatiquement
                              depuis l'EXIF des photos)
scripts/merge_sources.py   → fusionne avec les données Kobo du jour et
                              recalcule les statistiques du tableau de bord
```

Ces deux étapes sont déjà intégrées dans le workflow GitHub Actions
(`sync_and_deploy.yml`) : elles s'exécutent automatiquement chaque jour, à
la suite de la synchronisation Kobo.

### Ce que vous devez déposer dans le dépôt GitHub

Créez un dossier `legacy/` à la racine du dépôt, avec exactement :
```
legacy/
├── Base_donnees_Verification_PAP_EAK.xlsx   (volet vérification décret)
├── BDD_Enquete_PAR_EAK.xlsx                 (volet identification nouveaux PAP)
└── Images de terrain/
    ├── 20260713_114243.jpg
    ├── Nnelfup -Nkolo epse nko'o Philomène .jpg
    └── ...
```

Ces noms de fichiers sont **déjà calés sur vos fichiers réels** — le mapping
des colonnes dans `legacy_import.py` a été construit et testé directement
à partir des échantillons que vous avez transmis. Points déjà pris en compte :

- **Le masque décret** (`Base_donnees_Verification_PAP_EAK.xlsx`, feuille
  "Base_donnees", en-têtes ligne 4) : 30 PAP lues avec succès dans votre
  fichier. Ce volet ne contient pas de coordonnées GPS propres — la
  géolocalisation dépend donc entièrement des photos associées (voir
  ci-dessous).
- **Le masque nouveau** (`BDD_Enquete_PAR_EAK.xlsx`, feuille "BDD_Menages",
  codes ligne 2, données à partir de la ligne 4) : 9 PAP lues avec succès.
  ⚠️ **Anomalie détectée et corrigée automatiquement** : les colonnes
  "Longitude" et "Latitude" de ce masque sont en réalité **inversées** par
  rapport à leur libellé (vérifié empiriquement sur vos données réelles) —
  le script détecte et corrige cela via une plage de valeurs plausibles
  (latitude 1,5°-4,5°N / longitude 8,5°-13°E pour le corridor RN17).
- **Association photo ↔ PAP** : aucune colonne de référence photo n'étant
  renseignée dans vos masques, l'association se fait par **correspondance
  floue de noms** entre le nom du PAP et le nom de fichier — cela
  fonctionne pour les photos que vous avez renommées manuellement (ex.
  *"Nnelfup -Nkolo epse nko'o Philomène .jpg"*) : les 3 photos ainsi
  renommées dans votre échantillon ont été correctement associées, y
  compris malgré une variante orthographique ("Oba'a Jérôme" sur la photo
  vs "MBA'A Jerome" dans le masque — la correspondance floue gère ce type
  d'écart).
- **Photos horodatées non renommées** (type `20260713_114243.jpg`) : sans
  nom exploitable, elles ne peuvent pas être reliées automatiquement à une
  PAP précise. Sur votre échantillon, 20 d'entre elles contiennent des
  coordonnées GPS EXIF exploitables (les autres, prises avec un
  smartphone Samsung, n'ont pas de GPS valide dans les métadonnées). Le
  script les signale explicitement dans son journal d'exécution
  (`⚠ X photo(s) NON associée(s) automatiquement`) plutôt que de tenter un
  rapprochement hasardeux.

**Pour rattacher ces photos horodatées à la bonne PAP**, deux options :
1. **Renommez-les manuellement** (comme vous l'avez fait pour 3 d'entre
   elles) en incluant le nom du PAP et/ou le village — la correspondance
   floue fera le reste automatiquement au prochain passage.
2. Si vous disposez d'un carnet de terrain ou d'un ordre chronologique de
   passage, je peux adapter le script pour proposer un appariement par
   proximité de date/heure entre la photo et l'ordre de saisie du masque
   — dites-le-moi si cela vous semble pertinent.

### Garde-fou contre le double comptage (papier + Kobo)

Le zip de photos que vous avez transmis contenait des clichés datés du
13/07, du 16/07 **et du 21/07** — cette dernière date correspond au tout
premier jour de collecte via Kobo. Deux protections ont donc été ajoutées :

1. **Alerte explicite dans `legacy_import.py`** : toute photo horodatée à
   partir de la date de bascule vers Kobo (`KOBO_LAUNCH_DATE`, réglée par
   défaut au 21/07/2026 — modifiable en tête de fichier) est signalée
   séparément dans le journal d'exécution avec un avertissement 🔴 dédié,
   plutôt que d'être noyée parmi les photos simplement "non nommées".
2. **Dédoublonnage automatique dans `merge_sources.py`** : avant de
   fusionner les données Kobo et papier, le script recherche les PAP
   présentes dans les deux sources (même village + nom très similaire). En
   cas de correspondance forte, la fiche papier est **fusionnée** dans
   l'entrée Kobo (considérée comme la donnée la plus à jour) plutôt que
   comptée une seconde fois — avec, en bonus, complément automatique des
   coordonnées GPS si Kobo n'en a pas encore et que le papier en a.

Ce dédoublonnage a été testé avec un cas simulé (une même PAP présente
côté Kobo et côté papier) : la fusion et le recalcul des statistiques
fonctionnent correctement, sans double comptage.

⚠️ Cette correspondance reste probabiliste (nom + village similaires) : en
cas de doublon non détecté (orthographe trop différente) ou de faux
positif (deux personnes différentes au nom proche dans le même village),
une vérification manuelle ponctuelle reste recommandée, surtout dans les
premières semaines de transition papier → Kobo.



## Distinction des catégories sur le géoportail

Le formulaire Kobo étant "2 en 1", le géoportail distingue désormais
**3 catégories visuellement** (couleur + forme, pour rester lisible même
en impression noir et blanc ou pour les daltoniens) :

| Catégorie | Couleur | Forme |
|---|---|---|
| Vérification décret (Kobo) | Bleu | Cercle |
| Nouveaux PAP potentiels (Kobo) | Orange | Carré |
| Papier historique (pré-Kobo) | Gris | Triangle |

Chaque catégorie a sa propre case à cocher pour l'afficher/la masquer
indépendamment.

## Tableau de bord (effectifs + kilométrage)

Le panneau latéral du géoportail affiche désormais, mis à jour
automatiquement à chaque synchronisation :
- Le **total de PAP recensées**, ventilé par catégorie (décret / nouveau /
  papier historique)
- Le **kilométrage couvert par l'équipe d'enquête**, calculé à partir des
  PK (points kilométriques) déclarés dans les fiches — affiché comme
  "PK min → PK max" et l'étendue en kilomètres
- Le **nombre de villages couverts**, avec un décompte de PAP par village

Ces statistiques sont calculées par `merge_sources.py` et stockées dans
`site/data/stats.json`, que la page `index.html` va chercher au chargement.

⚠️ Le kilométrage est basé sur le champ PK saisi par les enquêteurs
(notation "12+300" ou décimale) : c'est une **étendue déclarative**, pas
une distance mesurée sur le terrain. Si des PK ne sont pas renseignés, ils
n'entrent pas dans le calcul (visible via "nb_points_avec_pk" dans
stats.json).

## Photos multiples par PAP, catégorisées automatiquement

Contrairement au premier lot de photos (majoritairement horodatées), vos
photos les plus récentes sont **toutes nommées de façon descriptive**, et
plusieurs photos peuvent documenter la **même PAP** (habitation, cultures,
tombes, pièce d'identité, portrait...). `legacy_import.py` gère désormais
cela nativement :

- Chaque photo est reliée à la PAP dont le nom correspond le mieux à son
  nom de fichier (et non plus une seule photo par PAP au maximum).
- Chaque photo est **catégorisée automatiquement** par mots-clés
  (habitation/concession/domaine → bâtiment, culture/parcelle/cacao/arbre
  fruitier → cultures, tombe/cimetière → tombe, CNI → pièce d'identité,
  stelle/église/chefferie → infrastructure communautaire, sinon → portrait
  du répondant).
- Le géoportail affiche désormais, dans l'info-bulle de chaque PAP, une
  **mini-galerie de toutes ses photos** avec leur catégorie, plutôt qu'une
  seule image.

Sur votre échantillon réel (40 photos, toutes nommées) : **les 40 photos
sont désormais associées automatiquement à 23 PAP différentes** (après
correction de 4 noms de fichiers trop ambigus), avec la répartition
suivante : bâtiment/concession (11), cultures (9), tombes (4), pièce
d'identité (2), infrastructure communautaire (2), infrastructure eau (1),
portrait (11).

Aucune photo non appariée à ce stade sur cet échantillon — si de nouvelles
photos horodatées (non renommées) sont ajoutées ultérieurement, elles
seront à nouveau signalées explicitement dans le journal d'exécution
plutôt que rattachées au hasard.

## Calcul précis du PK par référencement linéaire (sans attendre l'équipe topo)

En l'absence des fichiers PK officiels de l'équipe topographique, le
kilométrage peut désormais être **calculé géométriquement** : chaque PAP
géolocalisée est projetée sur le tracé réel de la RN17, et sa distance
cumulée le long de la route donne son PK — sans dépendre du PK saisi à la
main par les enquêteurs (souvent absent).

### Fichiers à déposer

Créez un dossier `legacy/gis/` avec, par exemple :
```
legacy/gis/
├── Linéaire_RN17.shp (+ .dbf, .shx, .prj, ...)   — ou .geojson, .kml, .gpx
└── Villages.shp (+ .dbf, .shx, .prj, ...)        — ou .geojson, .kml, .csv, .xlsx
```
La recherche des fichiers est **insensible à la casse et aux accents**, et
reconnaît plusieurs variantes de nommage (contenant "rn17"/"lineaire" pour
le tracé, "village" pour les villages) — inutile de renommer vos fichiers
exactement comme illustré, les noms que vous nous avez transmis
("Linéaire_RN17", "Villages") fonctionnent tels quels.

- **Le tracé RN17** : une ligne unique (ou plusieurs tronçons, même avec de
  petits écarts de calage entre eux — recollés automatiquement, voir plus
  bas). Un export OSM (comme celui que vous avez fourni) ou un tracé
  numérisé sur Google Earth/QGIS conviennent parfaitement.
- **Les villages** : un point par village avec son nom (colonne "nom",
  "name" ou "village", quelle que soit la langue). Si vous n'avez qu'un
  tableur avec des colonnes Nom/Latitude/Longitude, ça fonctionne aussi
  (pas besoin de format SIG).

### Ce que produit le calcul

- `site/data/pk_calcule.csv` : PK calculé pour chaque PAP géolocalisée,
  avec sa distance perpendiculaire au tracé (en mètres) et un indicateur
  de fiabilité (à moins de 2 km de l'axe par défaut — réglable via
  `DISTANCE_MAX_PLAUSIBLE_M` en tête de `calcul_pk_lineaire.py`).
- `site/data/villages_pk.csv` : PK de chaque village, trié du plus proche
  au plus loin d'Ebolowa — utile pour vérifier la cohérence de vos propres
  repères terrain.
- Le tableau de bord du géoportail utilise désormais **en priorité le PK
  calculé** (fiable et disponible pour toute PAP géolocalisée), et ne
  retombe sur le PK déclaré à la main que pour les PAP sans coordonnées
  GPS. Le nombre de PK issus de chaque méthode est visible dans
  `stats.json` (`nb_pk_calcule_geometriquement` / `nb_pk_declare_manuellement`).

### Résultat avec vos vrais fichiers

Ce calcul a été testé avec votre tracé RN17 réel (extrait OSM, 14 tronçons)
et votre couche de 265 villages. Quatre ajustements ont été nécessaires et
sont déjà intégrés :

- **Recollage automatique des tronçons** : votre tracé était fragmenté en
  11 segments avec de petits écarts de calage (quelques dizaines de mètres,
  typiques des exports OSM). Le script les recolle désormais automatiquement
  (tolérance 300 m, réglable via `STITCH_TOLERANCE_M`) — la longueur totale
  reconstituée est de **168,79 km**, cohérente avec le corridor
  Ebolowa–Akom II–Kribi.
- **Correction d'un encodage de caractères** : les noms de villages de votre
  fichier (ex. "Dikobé", "Élon") apparaissaient mal encodés ("DikobÃ©") —
  corrigé automatiquement.
- **Orientation du PK** : confirmée par l'équipe topographique, **le PK 0
  est à Ebolowa** (et non à Kribi). Le script détecte et corrige
  automatiquement le sens du tracé en repérant les points "Ebolowa" et
  "Kribi" dans votre couche de villages (`REFERENCE_PK0` /
  `REFERENCE_PK_FIN` en tête de `calcul_pk_lineaire.py`).
- **Double filtre des villages** : ~~seuls les villages à la fois (a) à moins
  de 100 m du tracé ET (b)~~ **seuls les villages figurant parmi les 58
  villages officiels des deux décrets** (`VILLAGES_DECRETS` — même liste
  que celle utilisée dans `merge_sources.py` et le formulaire Kobo) sont
  retenus — **sans condition de distance au tracé** (retirée sur demande).
  Une correspondance floue tolère les variantes orthographiques
  ("Nnelefoup" → "Nelefup") tout en évitant les confusions de numérotation
  ("Akom II" ne peut plus matcher "Akom I" ni "Aloum II", grâce à une
  double vérification du suffixe numérique et du mot de base).

Sur vos 39 PAP papier (dont 6 géolocalisées) : le PK a été calculé pour les
6, entre **PK 58,35 et 61,79 km** (secteur Aloum I/II/Nelefup, cohérent
avec leur position réelle, plus proche d'Ebolowa que de Kribi). Sur vos
265 villages, **66 correspondent à l'un des 58 villages officiels des
décrets** (contre 58 attendus — l'écart s'explique par des homonymes,
voir point de vigilance ci-dessous). **13 villages des décrets restent
introuvables** dans le fichier Villages.zip (orthographe trop différente,
ou absents du fichier) : Akom II Village, Avelezok, Ebemvok, Elone,
Foulassi II, Konda, Meyo-Ville, Mfenda, Mvieng, Mvilla-Yemissem, Nkolenyeng
Yemvang, Nkolmbonda, Nlomoto.

⚠️ **Point de vigilance suite au retrait du filtre de distance** : sans
condition de proximité au tracé, certaines correspondances se font sur des
**homonymes géographiquement éloignés** — ex. un village nommé "Assok"
trouvé à 54 km du tracé a été rapproché de "Assok I" (décret), alors qu'il
s'agit probablement d'une localité différente portant un nom similaire,
pas du véritable village du corridor. Le script signale automatiquement
(🔴 dans le journal d'exécution) toute correspondance à plus de 10 km du
tracé, pour un contrôle manuel ciblé plutôt qu'une confiance aveugle dans
le nom seul. Sur le test réel, une dizaine de correspondances de ce type
ont été signalées (10-56 km du tracé) — à vérifier avant utilisation pour
le calcul du kilométrage villageois.

Dès que de nouvelles PAP géolocalisées arriveront (via Kobo ou papier), leur
PK sera calculé automatiquement au prochain passage — aucun réglage
supplémentaire nécessaire de votre part.

⚠️ Si votre tracé RN17 est en réalité en zone UTM 33N plutôt que 32N
(selon la portion exacte du corridor), signalez-le-moi : c'est un seul
paramètre à ajuster (`CRS_PROJETE` en tête du script) pour garder des
distances exactes en mètres. Sur les coordonnées transmises, la zone 32N
s'est révélée correcte (résultats cohérents avec la géographie connue du
corridor).

Quand l'équipe topographique fournira enfin ses propres fichiers PK
officiels, il suffira de les substituer sans rien changer au reste du
pipeline — ce calcul géométrique n'est pas remplacé, il est simplement une
solution fiable en attendant.




