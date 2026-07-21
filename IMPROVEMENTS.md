# Idées d'amélioration pour wadscript

Backlog vivant d'idées non implémentées — pas un plan d'exécution,
juste un endroit où accumuler ce qui vaudrait la peine d'être fait un
jour. Chaque entrée : ce que c'est, pourquoi ça vaut le coup. Rien ici
n'est engagé tant que ce n'est pas explicitement demandé.

Ce qui a déjà été implémenté (vocabulaire/tables curatées, validation,
ergonomie du langage) est sorti de ce fichier et vit dans
[`CHANGELOG.md`](CHANGELOG.md) — ce fichier ne garde que ce qui reste
à faire, pour rester court et à jour.

## Génération procédurale

- **Primitives aléatoires.** Le but affiché de wadscript est la
  "géométrie procédurale", mais rien dans le langage n'introduit de
  hasard : deux exécutions du même script produisent toujours
  exactement le même niveau. Une fonction `random(min,max)` utilisable
  dans les expressions (typiquement à l'intérieur d'un `repeat`, pour
  varier une position ou un type de monstre) plus un flag `--seed
  <n>` pour la reproductibilité ouvrirait la porte à une vraie
  variation procédurale sans complexifier le cas simple (un script
  sans `random()` resterait déterministe).
- **Rotation/miroir pour `repeat`.** `repeat` ne fait que de la
  translation via les expressions dans les coordonnées — dupliquer une
  forme en la faisant pivoter (un donjon en étoile, une salle
  symétrique) demande de recalculer les points à la main pour chaque
  itération. Un mot-clé optionnel du genre `repeat i 4 { ... }
  rotate 90` (autour d'un pivot à préciser) couvrirait ce cas sans
  transformer `repeat` en moteur géométrique complet.
- **`floor`/`ceiling`/`light` expression-capables dans `repeat`.**
  Restriction actuelle assumée (voir CHANGELOG.md, "Ergonomie du
  langage") : seules les coordonnées sont expression-capables dans un
  `repeat`, pas `floor`/`ceiling`/`tag`/textures. Ça oblige
  `stairs.wsl` à dupliquer trois sectors presque identiques à la main
  (chaque marche +8 en hauteur) au lieu d'un seul `repeat i 3 { sector
  step_{i} { floor i * 8 ... } }`. Autoriser les expressions sur
  `floor`/`ceiling`/`light` (en gardant `tag`/textures hors-scope, qui
  ont besoin d'une valeur stable et pas d'un calcul) couvrirait
  rampes, escaliers en spirale et dégradés de lumière sans dupliquer
  de géométrie.
- **Constantes nommées au niveau du script.** Les seuls noms valides
  dans une expression aujourd'hui sont les variables de boucle d'un
  `repeat` englobant (voir `parse_atom`, parser.py) — un script qui
  répète la même largeur de couloir ou la même marge un peu partout
  n'a que le copier-coller. Un `const HALL_WIDTH = 256` déclaré une
  fois en tête de script et réutilisable dans toute expression de
  coordonnée réduirait ce risque de dérive, sans toucher à la logique
  des variables de `repeat` (qui resteraient prioritaires en cas de
  collision de nom, comme `angle north` aujourd'hui).
- **Opérateurs `/` et `%`.** `parse_term`/`parse_expr` (parser.py)
  n'implémentent que `+`, `-`, `*` et la négation unaire — calculer un
  centre (`largeur / 2`) ou répartir des éléments avec un motif
  cyclique dans un `repeat` (`i % 3`) demande de sortir la
  calculatrice avant d'écrire le script plutôt que d'exprimer le
  calcul directement.

## Sortie multi-niveaux

- **Plusieurs cartes dans un seul PWAD.** `wadwriter.py` écrit
  toujours exactement 11 lumps (un seul niveau) — le format WAD
  supporte nativement plusieurs niveaux à la suite dans un même
  fichier (c'est comme ça que `doom2.wad` contient MAP01..MAP32), mais
  rien dans wadscript ne le permet : un script a exactement une
  instruction `map`, et `wadscript.py` prend un seul fichier
  d'entrée. Utile pour générer un épisode complet en un seul appel
  (plusieurs fichiers `.wsl`, ou plusieurs blocs `map{}` dans un seul
  script, fusionnés en un PWAD multi-niveaux) plutôt que de fusionner
  les WADs à la main après coup.

## Organisation de projet

- **`include` capable de partager de la géométrie, pas seulement des
  conventions.** `_parse_script(restricted=True)` (parser.py) n'admet
  aujourd'hui que `defaults`/`texture_preset`/`include` imbriqué dans
  un fichier inclus — c'est délibéré pour que l'ordre de fusion
  n'ait jamais d'importance (contrairement à `offset relative_to`,
  documenté comme distinction volontaire dans CHANGELOG.md). Un
  niveau complexe reste forcément un seul gros fichier `.wsl` : rien
  ne permet de découper ses `sector`/`edge`/`thing` en plusieurs
  fichiers organisés par zone (une aile par fichier, par exemple),
  contrairement aux conventions partagées (`common.wsl`) qui
  fonctionnent déjà très bien pour ça. Un mot-clé distinct
  d'`include` (pour ne pas relâcher sa garantie d'indépendance à
  l'ordre) — `import "wing_east.wsl"`, par exemple — qui fusionnerait
  aussi la géométrie propre du fichier importé serait utile pour les
  niveaux qui dépassent la taille confortable d'un seul fichier.

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
  faut passer le WAD produit par un nodebuilder externe (BSP, ZenNode)
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
