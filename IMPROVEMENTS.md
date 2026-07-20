# Idées d'amélioration pour wadscript

Backlog vivant d'idées non implémentées — pas un plan d'exécution,
juste un endroit où accumuler ce qui vaudrait la peine d'être fait un
jour. Chaque entrée : ce que c'est, pourquoi ça vaut le coup. Rien ici
n'est engagé tant que ce n'est pas explicitement demandé.

## Fait

- **Vocabulaire / tables curatées (`tables.py`).** Les quatre points
  listés ci-dessous à l'origine sont implémentés : `SECTOR_SPECIALS`
  (15 entrées, vérifiées contre `ygd/doom2.ygd`), `LINEDEF_SPECIALS`
  étoffé (6 → 44 entrées : portes complètes, lifts, escaliers,
  crushers, effets de lumière, variantes switch), `THING_TYPES` étoffé
  (~24 → 100 entrées : tous les monstres non spécifiques à un port
  source, armures/munitions restantes, décorations, obstacles), et les
  tags symboliques (`tag lift_ouest`, auto-assignés et cohérents entre
  `sector{}` et `edge{}`, avec un avertissement si un nom n'est
  référencé qu'une seule fois dans le script — signe probable d'une
  faute de frappe). Voir README.md ("Curated symbol tables",
  "Symbolic tags") et `examples/lift_symbolic_tag.wsl`. Trois nouveaux
  exemples illustrent les catégories fraîchement ajoutées :
  `examples/stairs.wsl` (escalier), `examples/crusher.wsl` (crusher),
  `examples/secret_and_hazard.wsl` (secteurs `secret` et
  `damage_10pct`).
- **Validation.** Les deux points listés à l'origine sont faits :
  polygones auto-intersectants détectés (test segment-par-segment,
  appliqué à chaque boucle indépendamment — le `points{}` d'un secteur
  et chacun de ses `holes{}` — avec une erreur claire donnant les deux
  arêtes en cause) et secteurs imbriqués ("donuts") supportés via un
  nouveau champ `holes{}` sur `sector{}` (une boucle fermée de plus,
  soustraite de l'aire du secteur ; sa boucle interne est normalisée
  avec un sens de parcours inversé par rapport à un `points{}` normal,
  ce qui la fait automatiquement coïncider en anti-parallèle avec la
  boucle du secteur-îlot qu'elle entoure, sans rien de spécial à faire
  côté secteur-îlot). Vérifié avec un vrai nodebuilder (BSP 5.2) en
  plus de `--dump-geometry` et Yadex. Voir README.md ("Nested sectors
  (donuts)") et `examples/donut.wsl`. Limite restante, documentée dans
  "Known v1 limitations" du README : le chevauchement entre boucles
  (une boucle qui recouvre une autre sans partager exactement les
  mêmes arêtes) n'est pas détecté, seule l'auto-intersection de chaque
  boucle prise isolément l'est.

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
