# Didacticiel wadscript

Ce didacticiel construit un petit niveau Doom II pas à pas : une pièce,
puis un couloir relié par une porte, un monstre, et une sortie. Pour la
référence complète de la grammaire et des tables symboliques, voir
[README.md](README.md). Pour l'analyse du format WAD sous-jacent, voir
[../ANALYSE_wad.md](../ANALYSE_wad.md).

Prérequis : Python 3 (aucune dépendance externe), et idéalement Yadex
déjà compilé dans ce dépôt (`../obj/0/yadex`) pour visualiser le
résultat au fur et à mesure.

## Étape 1 — Une pièce vide

Un script wadscript décrit un niveau comme une liste de **secteurs**
(des pièces, sous forme de polygones fermés) et de **things** (joueur,
monstres, objets). Créez `tuto.wsl` :

```
map "MAP01"

sector chambre {
  points {
    (0,0)
    (256,0)
    (256,256)
    (0,256)
  }
}
```

`map "MAP01"` est obligatoire et donne son nom au niveau. `sector
chambre { points { ... } }` déclare une pièce carrée de 256×256 : les 4
coins, dans l'ordre que vous voulez (peu importe le sens de parcours,
horaire ou antihoraire — wadscript s'en charge automatiquement).

Compilez-le, mais sans encore écrire de WAD, juste pour inspecter ce
qui a été compris :

```sh
python3 wadscript.py tuto.wsl -o /tmp/tuto.wad --dump-geometry
```

```
warning: script has no 'thing player1_start ...' -- the level has no player 1 start
map 'MAP01'
vertices (4): ...
sectors (1): ...
sidedefs (4): ...
linedefs (4):
  0: v0->v1 flags=0x0001 special=0 tag=0 sd1=0 sd2=-1
  ...
things (0):
```

wadscript a dérivé tout seul les 4 vertices et les 4 linedefs (tous à
un seul côté, `flags=0x0001` = impassible, puisqu'aucun secteur voisin
ne partage ces murs) à partir du seul polygone que vous avez déclaré.
L'avertissement sur `player1_start` est normal à ce stade — on n'a pas
encore placé le joueur.

## Étape 2 — Placer le joueur

Ajoutez à la fin du fichier :

```
thing player1_start at (32,32) angle 90
```

`at (x,y)` place le thing, `angle` est la direction regardée en degrés
(0 = est, 90 = nord, etc.). Relancez `--dump-geometry` : l'avertissement
a disparu, et `things (1):` montre `type=1` (le doomednum de
`player1_start`, résolu automatiquement depuis la table symbolique de
`tables.py`).

## Étape 3 — Écrire le WAD et l'ouvrir dans Yadex

Sans `--dump-geometry`, wadscript écrit vraiment le fichier :

```sh
python3 wadscript.py tuto.wsl -o /tmp/tuto.wad
../obj/0/yadex -g doom2 -pw /tmp/tuto.wad
```

Au prompt `yadex:`, tapez `e map01` pour ouvrir le niveau : vous devriez
voir un carré avec le marine positionné dans le coin bas-gauche.

**Note** : les lumps SEGS/SSECTORS/NODES/REJECT/BLOCKMAP sont
volontairement vides (à reconstruire par un nodebuilder externe comme
ZenNode avant de jouer dans un port source) — Yadex n'en a pas besoin
pour éditer, ce qui en fait l'outil de vérification idéal ici.

## Étape 4 — Une deuxième pièce, reliée automatiquement

Ajoutez un second secteur qui **partage un mur** avec `chambre` — le
segment `(256,0)-(256,256)`, le côté droit de `chambre`, redevient le
côté gauche de `couloir` :

```
sector couloir {
  floor 0
  ceiling 112
  light 120
  points {
    (256,0)
    (512,0)
    (512,256)
    (256,256)
  }
}
```

Relancez `--dump-geometry`. Le nombre de vertices passe de 4 à 6 (les 2
coins partagés ne sont pas dupliqués), et un des linedefs bascule tout
seul en `flags=0x0004` (deux côtés) avec `sd1`/`sd2` pointant chacun
vers un secteur différent — **sans avoir rien déclaré de plus** que les
deux polygones. C'est le principe central de wadscript : les murs
communs entre secteurs deviennent des linedefs à deux côtés
automatiquement, avec le texturage des marches (upper/lower) déduit
tout seul de la différence de hauteur de plafond/sol (ici `ceiling 128`
vs `ceiling 112` → une marche apparaît côté plafond, générée toute
seule avec la texture murale par défaut).

## Étape 5 — Transformer le mur commun en porte

Pour attacher une action (ici, une porte) à un mur précis, on le cible
par ses deux coordonnées de coin avec un bloc `edge{}` :

```
edge (256,0)-(256,256) {
  special door_use
  texture chambre { upper "BIGDOOR2" middle "-" lower "-" }
  texture couloir { upper "BIGDOOR2" middle "-" lower "-" }
}
```

`special door_use` résout vers le linedef special 1 (porte DR,
réutilisable, déclenchée par usage — voir la table complète dans
[README.md](README.md#curated-symbol-tables)). Les deux blocs `texture
<secteur> { ... }` posent la texture `BIGDOOR2` sur le côté de chaque
secteur — sans ça, wadscript aurait mis la texture murale par défaut,
ce qui aurait l'air d'un mur normal, pas d'une porte.

L'ordre des coordonnées de l'`edge` n'a pas besoin de correspondre à
l'ordre dans lequel un secteur ou l'autre a déclaré ce coin — seule la
paire de points compte.

## Étape 6 — Ajouter un monstre

```
thing zombieman at (400,128) angle 180
```

`zombieman` (doomednum 3004) fait partie de la table curatée des
things courants. Pour un type non listé, utilisez l'échappatoire
`raw <doomednum>`, par exemple `thing raw 3001 at (...) angle 0` pour
un imp (qui, lui, est déjà dans la table sous le nom `imp` — mais
l'échappatoire marche pour tout ce qui n'y est pas).

## Étape 7 — Une sortie

Ajoutez une troisième pièce et une sortie sur son mur le plus éloigné :

```
sector arene {
  floor 0
  ceiling 160
  light 200
  points {
    (512,0)
    (768,0)
    (768,256)
    (512,256)
  }
}

edge (768,0)-(768,256) {
  special exit_level
  texture arene { middle "SW1EXIT" }
}
```

Ce mur n'est bordé que par un seul secteur (`arene`) : c'est donc
automatiquement un linedef à un seul côté, sur lequel `special
exit_level` (11, "fin de niveau") est posé directement — pas besoin de
préciser deux blocs `texture` puisqu'il n'y a qu'un seul côté.

## Étape 8 — Personnaliser les valeurs par défaut

Plutôt que de répéter `floor_flat`/`ceiling_flat`/etc. sur chaque
secteur, un bloc `defaults{}` en tête de fichier change les valeurs de
repli (celles utilisées quand un secteur ne précise pas le champ) :

```
defaults {
  floor_flat "FLOOR4_8"
  ceiling_flat "CEIL3_5"
  wall_texture "STARTAN3"
  middle_texture "-"
  light 160
}
```

Le fichier complet correspond maintenant à
[`examples/three_rooms.wsl`](examples/three_rooms.wsl) — comparez si
besoin.

## Quand ça casse

wadscript refuse d'écrire un WAD tant qu'il reste une erreur, et
rapporte toujours un numéro de ligne. Par exemple, cibler un mur qui
n'existe pas :

```
edge (999,999)-(1000,1000) {
  special door_use
}
```

donne :

```
tuto.wsl:12: error: edge override (999, 999)-(1000, 1000) does not match any wall segment derived from the sectors
```

et **aucun fichier n'est écrit**. C'est volontaire : mieux vaut un
échec net qu'un WAD silencieusement à moitié correct. Les erreurs
courantes (polygone à moins de 3 points, mur partagé par plus de 2
secteurs, nom de thing/special inconnu sans `raw`, texture de plus de 8
caractères...) sont listées dans [README.md](README.md#known-v1-limitations)
et la section validation du plan d'origine.

## Pour aller plus loin

- Référence complète de la grammaire, des tables symboliques et de
  l'algorithme de dérivation géométrique : [README.md](README.md).
- Étendre les tables (specials, things) : `tables.py` — ce sont de
  simples dictionnaires Python, faciles à compléter.
- Une fois le WAD généré, faites-le passer par un nodebuilder externe
  (ZenNode, BSP...) avant de le lancer dans un port source ou
  `doom2.exe`.
