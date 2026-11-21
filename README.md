<p align="center">
  <img src="https://upload.wikimedia.org/wikipedia/commons/f/f4/Orc_grunt_by_Lucas_Salcedo_%28cropped%29.jpg" alt="Grunt orc de Warcraft" width="320">
</p>

<h1 align="center">WebScrapingWarcraft</h1>

<p align="center">
  Récupère les répliques vocales françaises de <b>Warcraft III</b> depuis le Wiki WoW :<br>
  texte, URL du son, et fichier audio converti en mp3.
</p>

---

## Ce que fait le projet

Le script `scrapping.py` récupère les répliques de Warcraft III pour les 4 races, en **français** ([wowwiki.fandom.com](https://wowwiki.fandom.com/fr/wiki/R%C3%A9pliques_de_Warcraft_III)) et en **anglais** ([warcraft.wiki.gg](https://warcraft.wiki.gg/wiki/Quotes_of_Warcraft_III)) :

| Race (clé) | FR | EN | JSON | Audio |
|---|---|---|---|---|
| Humain / Human (`Human`) | 536 | 492 (+82 repli FR) | `data/<lang>/Human.json` | `MP3/<lang>/Human/` |
| Orc (`Orc`) | 475 | 385 (+66) | `data/<lang>/Orc.json` | `MP3/<lang>/Orc/` |
| Elfe de la nuit / Night Elf (`Night_Elf`) | 599 | 391 (+141) | `data/<lang>/Night_Elf.json` | `MP3/<lang>/Night_Elf/` |
| Mort-vivant / Undead (`Undead`) | 453 | 330 (+117) | `data/<lang>/Undead.json` | `MP3/<lang>/Undead/` |

Pour **chaque réplique**, il extrait le texte, l'URL du clip et le nom de l'unité / héros / section, télécharge le clip, le convertit en **mp3** (`pydub` + `ffmpeg`) et enregistre les métadonnées dans le JSON de la race. Un run complet (`--all`) télécharge ~4 070 clips (dont ~406 clips FR de repli côté EN) en ~3 minutes (8 téléchargements en parallèle).

### Format des données

Audio : `MP3/<lang>/<Race>/<Unité_ou_Héros>/<id_g>-<début_de_la_réplique>.mp3` (`lang` = `fr` ou `en`; `id_g` repart de 0 pour chaque langue; les `/` des noms d'unités sont remplacés par `_`).

Chaque entrée du JSON (clé `"{id}-{nom}"`) :

```json
{
    "id_g": 536,
    "id": 0,
    "lang": "fr",
    "race": "Orc",
    "replique": "__amélioration_terminée.",
    "url": "https://static.wikia.nocookie.net/...ogg",
    "name": "Alertes",
    "unit_key": "alerts",
    "fallback_from": null,
    "file_name": "améliorationterminée"
}
```

### Unités sans répliques EN : repli sur le FR

Quand une unité n'a **aucune** réplique EN (`Alertes`, `Bâtiments`, `Chimère`…), ou qu'elle est marquée `"fallback_fr": true` dans `unit_names.json` (ex. `kodo_beast`, 1 réplique EN seulement), ses clips FR sont ajoutés au jeu EN : texte et audio restent en français et l'entrée porte `"fallback_from": "fr"` (les vraies répliques EN ont `null`). Le dossier prend le nom EN de l'unité, ou son nom FR s'il n'y en a pas. Les pages FR sont donc aussi lues avec `--en`, mais les fichiers FR ne sont écrits qu'avec `--fr`/`--all`. Pour exclure ces clips : `fallback_from == null`. Le total EN passe ainsi de 1 598 à 2 004 clips.

### Lien entre unités FR et EN

`unit_names.json` (versionné) relie les noms de sections : `race → unit_key → {fr, en}` (`fr` peut être une liste quand une unité a plusieurs formes; `null` si l'unité n'existe que d'un côté). Chaque réplique porte le `unit_key` correspondant : filtrer sur `unit_key` donne les répliques FR et EN d'une même unité (ex. `footman` ↔ Fantassin).
`python scrapping.py --check-names` (sans rien télécharger) liste les noms de sections absents de la table (`UNMAPPED`, à ajouter à `unit_names.json`) puis affiche, par race et par unité, le nombre de répliques FR / EN, l'écart et un statut (`ok`, `count differs`, `FR only`, `EN only`), ainsi que les entrées de la table qui n'existent plus sur les wikis.

## Prérequis

- **Python 3.10+** (testé avec 3.12)
- **ffmpeg** (et `ffprobe`) installé et accessible dans le `PATH` : `pydub` s'en sert pour décoder et encoder l'audio
  - Debian / Ubuntu : `sudo apt install ffmpeg`
  - macOS : `brew install ffmpeg`
  - Windows : `winget install ffmpeg` ou [ffmpeg.org](https://ffmpeg.org/download.html)
- Une connexion Internet
- Environ 100 Mo d'espace disque libre (les mp3 pèsent ~25 Mo)

## Installation

```bash
git clone https://github.com/PierreSaumet/WebScrapingWarcraft.git
cd WebScrapingWarcraft

python3 -m venv env
source env/bin/activate          # Windows : env\Scripts\activate
pip install -r requirements.txt
```

## Utilisation

```bash
source env/bin/activate
python scrapping.py            # = --all : FR + EN
python scrapping.py --fr       # français seulement  (-f)
python scrapping.py --en       # anglais seulement   (-e)
python scrapping.py --check-names   # vérifie unit_names.json, sans télécharger
```

Sortie attendue (`--all`) :

```
Scraped 3661 quotes in 7.0s, downloading audio (8 at a time)...
[3661/3661] 100.0%  elapsed  141.0s  eta    0.0s
Done. 3661/3661 clips downloaded successfully in 142.3s.
```

Les JSON sont créés dans `data/<lang>/` et les clips dans `MP3/<lang>/`.

## À vérifier avant et après un lancement

**Avant**

- [ ] `ffmpeg -version` et `ffprobe -version` répondent (sinon : erreurs de décodage sur tous les clips).
- [ ] L'environnement virtuel est activé et `pip install -r requirements.txt` est passé.
- [ ] Vous avez de la place sur le disque.

**Après**

- [ ] La dernière ligne indique `Done. N/N clips downloaded successfully`. Chaque téléchargement est retenté jusqu'à 4 fois (attente 1, 2, 4 s) : le CDN renvoie parfois un 403 ponctuel. Les échecs définitifs sont listés un par un (`Failed to download ...`), ils ne bloquent pas le reste; relancez la langue concernée.
- [ ] Aucun message `WARNING: found 0 quotes for <lang>/<race>` ni `UNMAPPED ...`. S'il apparaît, la page n'a pas pu être lue (voir la section suivante).
- [ ] Les JSON existent dans `data/<lang>/` et `MP3/<lang>/` contient un sous-dossier par race.
- [ ] Aucune entrée avec `"name": null` dans les JSON : ce serait le signe que le wiki a changé la structure de ses titres de sections.

## Particularités à connaître

- **Cloudflare (FR)** : le wiki est protégé par un challenge JavaScript. Avec `requests` seul, il renvoie une page « Just a moment... » (HTTP 403) sans lever d'erreur, et le script ne trouverait aucune réplique. Le projet utilise donc `cloudscraper`. Ne le remplacez pas par `requests`.
- **Anti-bot (EN)** : warcraft.wiki.gg bloque `cloudscraper` et curl sur les pages HTML, mais son API MediaWiki (`api.php?action=parse`) répond à `requests` avec un User-Agent descriptif. Le côté EN passe donc par l'API.
- **Protection des données existantes** : si une (langue, race) ne renvoie aucune réplique (page bloquée ou mise en page modifiée), elle est **ignorée** : son dossier `MP3/<lang>/<Race>/` et son JSON ne sont pas touchés. Pour une race qui a réussi, `MP3/<lang>/<Race>/` est **supprimé puis retéléchargé** à chaque lancement : ne placez rien d'autre dedans.
- **Faux mp3** : les fichiers sources sont en réalité des `.ogg`. Le script laisse `ffmpeg` détecter le format à la lecture et n'impose `mp3` qu'à l'export. Forcer `format="mp3"` en entrée fait échouer tous les décodages.
- **URL audio en `src` ou `data-src`** : selon la page servie, le wiki met l'URL du clip dans `src` ou (chargement différé) dans `data-src`. Le parseur accepte les deux et ignore les répliques sans URL.
- **Deux variantes de titres** : le wiki sert au hasard deux structures de titres de sections (`<span class="mw-headline">` ou `<h2 id=...>`). `parse_race_page()` gère les deux.

## Configuration

| Réglage | Où | Défaut |
|---|---|---|
| Téléchargements simultanés | `MAX_WORKERS` dans `scrapping.py` | `8` |
| Pages / races scrapées | `SOURCES` dans `scrapping.py` | 4 races × 2 langues |

## Ce qui n'est pas versionné

`env/`, `MP3/`, `data/` et les JSON générés sont exclus par le `.gitignore` (`unit_names.json` est, lui, versionné). Lancez le script pour les recréer.

## Crédits et droits

- Répliques et sons : © Blizzard Entertainment, contenu du Wiki WoW (Fandom, FR) et de warcraft.wiki.gg (EN), sous licence CC BY-SA. Ce dépôt ne contient aucun fichier audio.
- Image : *Orc grunt* par Lucas Salcedo, [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/), via [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Orc_grunt_by_Lucas_Salcedo_(cropped).jpg).
- Projet non officiel, sans lien avec Blizzard Entertainment.
