# Casino Phone — bot Discord

Un casino entièrement en images de téléphone : chaque joueur a son téléphone (« Moha Phone », « Moha Casino »… d'après son nom d'utilisateur Discord), avec ses apps, son argent et ses jeux. Monnaie **virtuelle** en euros : rien ne s'achète ni ne se retire en vrai.

## Déploiement (Railway)

1. Mets tous les fichiers (et le dossier `fonts/`) dans ton dépôt.
2. Railway détecte le `Dockerfile` automatiquement.
3. Variables d'environnement : `TOKEN` (token du bot) et `DATA_DIR=/data` (avec un volume monté sur `/data`).
4. Sur le portail développeur Discord, active les intents **Server Members** et **Message Content**.

La base est `DATA_DIR/phone_casino.db` (nouvelle base : l'ancienne `casino.db` en jetons n'est pas reprise).

## Commandes joueurs (prefix par défaut `$`)

| Commande | Effet |
|---|---|
| `$phone` | Allume le téléphone (écran verrouillé puis accueil) |
| `$casino` | App Casino : les 19 jeux |
| `$mines 5`, `$bj 2,50`, `$crash tout`… | Ouvre directement un jeu avec une mise |
| `$wallet` · `$banque` · `$crypto` · `$metiers` | Apps argent |
| `$profil` · `$top` · `$boutique` · `$fair` · `$aide` | Autres apps |
| `$daily` · `$work` | Récompense quotidienne · service du métier |
| `$guide [jeu]` | Règles de chaque jeu (embeds + menu déroulant) |
| `$verify <server> <client> <nonce>` | Vérifier un tirage provably fair |

## Commandes staff

`$addmoney` `$removemoney` `$setmoney` `$resetbalance` (Owner+) · `$allow` `$unallow` `$allowed` (Owner+) ·
`$additem <prix> [@rôle] <nom>` `$delitem <id>` (Owner+) · `$config [clé valeur]` (Sys+) ·
`$wl` `$owner` `$sys` et leurs `un…` · `$prefix` `$setlog` `$wipeeconomy` (Buyer).

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
