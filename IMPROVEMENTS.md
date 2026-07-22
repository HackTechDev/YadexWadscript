# Idées d'amélioration pour wadscript

Backlog vivant d'idées non implémentées — pas un plan d'exécution,
juste un endroit où accumuler ce qui vaudrait la peine d'être fait un
jour. Chaque entrée : ce que c'est, pourquoi ça vaut le coup. Rien ici
n'est engagé tant que ce n'est pas explicitement demandé.

Ce qui a déjà été implémenté (vocabulaire/tables curatées, validation,
ergonomie du langage) est sorti de ce fichier et vit dans
[`CHANGELOG.md`](CHANGELOG.md) — ce fichier ne garde que ce qui reste
à faire, pour rester court et à jour.

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
- **`wad2wsl.py` : décompiler tous les niveaux d'un WAD en un seul
  appel.** Aujourd'hui `--map` ne décompile qu'un seul niveau à la fois
  (le seul présent, ou celui nommé explicitement) — symétrique de la
  limitation ci-dessus côté compilation. Un flag genre `--all` qui
  parcourt chaque marqueur de niveau du WAD et écrit un `.wsl` par
  niveau éviterait de rappeler l'outil à la main une fois par carte
  pour un WAD comme `doom2.wad`.

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

## Langage

- **Un `sector{}` capable de plusieurs polygones disjoints.**
  Aujourd'hui un secteur DSL n'a qu'un seul contour extérieur
  (`points{}`) plus des trous imbriqués dedans (`holes{}`) — il ne peut
  pas exprimer plusieurs morceaux totalement séparés partageant le même
  numéro de secteur (un patchwork de pièces éloignées avec la même
  hauteur de plafond et le même effet spécial, par exemple). C'est
  exactement le cas que `wad2wsl.py` rencontre en décompilant un WAD
  existant (voir CHANGELOG.md, section "Décompilation") et contourne en
  écrivant plusieurs blocs `sector{}` synthétiques (`s<N>`, `s<N>b`,
  ...) aux attributs dupliqués — ce qui casse un special qui cible ce
  secteur *par son numéro* plutôt que par `tag` (un seul des morceaux
  serait affecté). Un `points{}` répétable (plusieurs contours
  extérieurs dans un seul `sector{}`) supprimerait le besoin de cette
  synthèse côté décompilation, et permettrait aussi d'écrire ce genre
  de secteur à la main côté compilation.

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
