# Idées d'amélioration pour wadscript

Backlog vivant d'idées non implémentées — pas un plan d'exécution,
juste un endroit où accumuler ce qui vaudrait la peine d'être fait un
jour. Chaque entrée : ce que c'est, pourquoi ça vaut le coup. Rien ici
n'est engagé tant que ce n'est pas explicitement demandé.

## Vocabulaire / tables curatées (`tables.py`)

- **Table `SECTOR_SPECIALS`.** Actuellement vide (voir README.md,
  section "Curated symbol tables") — `sector { special ... }` n'accepte
  que `raw <int>`. Un petit ensemble curaté (secret, dégâts au sol
  5%/10%/20%, clignotements, plancher qui remonte...) rendrait les
  scripts plus lisibles, sur le même modèle que `LINEDEF_SPECIALS`
  (vérifié contre `ygd/doom2.ygd` avant d'ajouter quoi que ce soit).
- **Étoffer `LINEDEF_SPECIALS`.** Seulement 6 entrées aujourd'hui
  (portes, lift, sorties, téléport). Manquent : portes qui se
  referment seules, escaliers, crushers, effets de lumière
  (clignotement, strobe), variantes "switch" (S1/SR) des mêmes actions
  déjà couvertes en walk-trigger.
- **Étoffer `THING_TYPES`.** ~24 entrées, essentiellement les
  monstres/objets les plus courants du premier niveau de Doom II.
  Manquent la plupart des monstres (spectre, caco, baron, revenant...),
  armures/munitions restantes, décorations, obstacles.
- **Tags symboliques.** `tag 5` est un entier brut ; une table de noms
  (`tag lift_ouest` → un entier auto-assigné et cohérent entre le
  `sector{}` et l'`edge{}` qui le référence) éliminerait toute une
  classe d'erreurs de copier-coller (tag qui ne correspond pas).

## Validation

- **Polygones auto-intersectants.** Non détectés aujourd'hui — un
  secteur dont les arêtes se croisent produirait une géométrie WAD
  invalide sans erreur claire à la compilation.
- **Secteurs imbriqués ("donuts").** Limitation documentée du v1 :
  l'algorithme de dérivation d'arêtes ne gère que l'adjacence simple,
  pas un secteur-îlot à l'intérieur d'un autre (ex. un pilier au milieu
  d'une pièce). Demanderait de repenser le groupement d'arêtes pour
  distinguer un contour extérieur d'un contour intérieur.

## Ergonomie du langage

- **Coordonnées relatives.** Aujourd'hui, chaque secteur est en
  coordonnées absolues — composer plusieurs pièces demande de calculer
  soi-même les décalages. Une syntaxe du genre `sector b relative_to a
  east 0 { ... }` ou un simple `offset (dx,dy)` appliqué à tout un bloc
  de points réduirait beaucoup l'arithmétique manuelle.
- **Motifs répétitifs (escaliers, grilles de pièces).** Pas de moyen
  de générer N sous-secteurs similaires (un escalier de 8 marches, une
  grille de salles type donjon) sans les écrire à la main un par un.
  Un mini-mécanisme de répétition (`repeat 8 { ... }` avec une variable
  d'itération utilisable dans les coordonnées) couvrirait le cas le
  plus fréquent sans transformer le DSL en langage de programmation
  complet.
- **Validation des noms de texture/flat contre un WAD réel.** Le
  texturage n'est actuellement qu'un passe-plat de chaînes de
  caractères (troncature à 8 caractères vérifiée, mais pas l'existence
  de la texture). Une option `--check-textures <iwad>` qui vérifie les
  noms contre PNAMES/TEXTURE1/les flats d'un iwad donné attraperait les
  fautes de frappe (`"STARTAN"` au lieu de `"STARTAN3"`) avant le
  chargement dans un éditeur.

## Outillage

- **Vraie suite de tests.** `tests/` ne contient qu'une note pour
  l'instant (voir `tests/README.md`). Tests dorés (golden-byte) sur
  `wadwriter.py`, cas `Script`→`LevelData` calculés à la main pour
  `geometry.py` — permettrait de refactorer sans tout re-vérifier à la
  main dans Yadex à chaque fois.
- **Mode `--lint`.** Valider un script sans exiger de chemin de sortie
  (`-o`) ni écrire quoi que ce soit — utile pour un hook d'édition ou
  une CI légère.
- **Intégration nodebuilder optionnelle.** Le README rappelle qu'il
  faut passer le WAD produit par un nodebuilder externe (ZenNode, BSP)
  avant de pouvoir y jouer. Un flag `--build-nodes <binaire>` qui
  invoque cet outil automatiquement après l'écriture éviterait cette
  étape manuelle systématique.

## Cibles alternatives (décisions déjà tranchées, à ne rouvrir que si le besoin change)

- **Format Hexen / scripts ACS.** Explicitement écarté au moment de la
  conception (voir la discussion d'origine) au profit du format
  Doom/Doom II classique, plus simple. Resterait pertinent si le besoin
  glisse un jour vers du scripting de comportement in-game plutôt que
  de la géométrie procédurale pure.
- **Export UDMF.** Écarté pour la même raison (complexité largement
  supérieure pour un "petit" langage). Le format actuel (arêtes
  dérivées automatiquement) se transposerait assez directement vers
  UDMF si le besoin de ports source modernes se faisait sentir.
