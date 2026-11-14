# Casino Phone — bot Discord

Un casino entièrement en images de téléphone : chaque joueur a son téléphone (« Moha Phone », « Moha Casino »… d'après son nom d'utilisateur Discord), avec ses apps, son argent et ses jeux. Monnaie **virtuelle** en euros : rien ne s'achète ni ne se retire en vrai.

## Déploiement (Railway)

1. Mets tous les fichiers (et le dossier `fonts/`) dans ton dépôt.
2. Railway détecte le `Dockerfile` automatiquement.
3. Variables d'environnement : `TOKEN` (token du bot) et `DATA_DIR=/data` (avec un volume monté sur `/data`).
4. Sur le portail développeur Discord, active les intents **Server Members** et **Message Content**.

La base est `DATA_DIR/phone_casino.db` (nouvelle base : l'ancienne `casino.db` en jetons n'est pas reprise).

## Le circuit de l'argent

| Où | Monnaie | Sert à |
|---|---|---|
| **Banque** | euros | Reçoit tout ce qu'on gagne hors casino (daily, salaire, intérêts du livret, rakeback). Paie la boutique, les virements et les formations. |
| **Wallet** | crypto | On y achète de la crypto avec la banque (frais 1 %) et on la revend vers la banque (frais 1,5 %). 15 cryptos au cours réel. |
| **Casino** | crypto | Se joue uniquement en crypto. La mise est saisie en euros puis prise dans la crypto choisie, au cours du moment. Les gains reviennent dans la même crypto. |

Un joueur sans crypto qui ouvre un jeu tombe sur un écran qui explique les 3 étapes, avec un bouton pour acheter directement (l'USDT est proposé car sa valeur est stable). Les frais se règlent avec `$config buy_fee_bp` et `$config sell_fee_bp` (100 = 1 %).

## Commandes joueurs (prefix par défaut `$`)

| Commande | Effet |
|---|---|
| `$phone` | Allume le téléphone (écran verrouillé puis accueil) |
| `$debutant` | Guide du débutant : banque, wallet, crypto, casino |
| `$casino` | App Casino : les 19 jeux |
| `$mines 5`, `$bj 2,50`, `$crash tout`… | Ouvre directement un jeu avec une mise (en euros, payée en crypto) |
| `$banque` · `$wallet` · `$marche` · `$metiers` | Apps argent |
| `$profil` · `$top` · `$boutique` · `$fair` · `$aide` | Autres apps |
| `$daily` · `$work` | Récompense quotidienne · service du métier (versés en banque) |
| `$guide [jeu]` | Guide du débutant et règles de chaque jeu (embeds + menu déroulant) |
| `$verify <server> <client> <nonce>` | Vérifier un tirage provably fair |

## Commandes staff

`$addmoney` `$removemoney` `$setmoney` `$resetbalance` (Owner+, agissent sur la banque) · `$allow` `$unallow` `$allowed` (Owner+) ·
`$config [clé valeur]` (Sys+) · `$wl` `$owner` `$sys` et leurs `un…` · `$prefix` `$setlog` `$wipeeconomy` (Buyer).

### Boutique

| Commande | Effet |
|---|---|
| `$additem` | Ouvre le panneau de création : type, nom, description, prix, stock, limite par joueur, rôle ou salon des commandes |
| `$edititem <id>` | Même panneau, pour modifier un article |
| `$delitem <id>` | Retire l'article de la vente (l'historique est gardé) |
| `$items` | Liste des articles, stocks et ventes |
| `$commandes` | Commandes en attente de livraison |
| `$livrer <n°>` · `$rembourser <n°>` | Clore une commande (aussi possible avec les boutons) |
| `$setorders #salon` | Salon où arrivent les commandes à livrer (Sys+) |

Trois types d'articles :
- **Rôle** : donné automatiquement à l'achat (mon rôle doit être au-dessus).
- **Nitro / Nitro Boost** : la commande arrive dans le salon des commandes avec deux boutons, **Livré** et **Rembourser**. Le staff envoie le Nitro au joueur puis clique sur Livré, et le joueur reçoit un MP.
- **Autre récompense** : n'importe quoi d'autre (carte cadeau, objet, service…), même fonctionnement que le Nitro.

## Fichiers

| Fichier | Rôle |
|---|---|
| `bot.py` | Discord : le téléphone, les boutons, les commandes |
| `core.py` | Base de données, économie, provably fair, tables de gains |
| `games.py` | Logique des 19 jeux |
| `gfx.py` | Moteur de rendu (skia) |
| `screens_apps.py` / `screens_games.py` | Dessin des écrans |
| `crypto_feed.py` | Cours en direct (Binance, secours CoinGecko) |
| `guide.py` | Textes du guide |
