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

Le script `scrapping.py` parcourt les 4 pages de répliques de Warcraft III du [wowwiki.fandom.com (FR)](https://wowwiki.fandom.com/fr/wiki/R%C3%A9pliques_de_Warcraft_III) :

| Race | Fichier JSON produit | Dossier audio |
|---|---|---|
| Humain | `Humain.json` | `MP3/Humain/` |
| Orc | `Orc.json` | `MP3/Orc/` |
| Elfe de la nuit | `Elfe_de_la_nuit.json` | `MP3/Elfe_de_la_nuit/` |
| Mort-vivant | `Mort-vivant.json` | `MP3/Mort-vivant/` |

Pour **chaque réplique** trouvée, il :

1. extrait le texte de la réplique, l'URL du clip audio et le nom de l'unité / du héros / de la section ;
2. télécharge le clip et le convertit en **mp3** (via `pydub` + `ffmpeg`) ;
3. enregistre les métadonnées dans le JSON de la race.

Un run complet récupère environ **2 063 répliques** (536 Humain, 475 Orc, 599 Elfe de la nuit, 453 Mort-vivant) en 1 à 2 minutes avec 8 téléchargements en parallèle.

### Format des données

Dossier audio : `MP3/<Race>/<Unité_ou_Héros>/<id_g>-<début_de_la_réplique>.mp3`

Chaque entrée du JSON (clé `"{id}-{nom}"`) :

```json
{
    "id_g": 536,
    "id": 0,
    "race": "Orc",
    "replique": "__amélioration_terminée.",
    "url": "https://static.wikia.nocookie.net/...ogg",
    "name": "Alertes",
    "file_name": "améliorationterminée"
}
```

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
python scrapping.py
```

Sortie attendue :

```
Scraped 2063 quotes in 6.2s, downloading audio (8 at a time)...
[2063/2063] 100.0%  elapsed   88.4s  eta    0.0s
Done. 2063/2063 clips downloaded successfully in 94.6s.
```

Les fichiers `*.json` sont créés à la racine du projet et les clips dans `MP3/`.

## À vérifier avant et après un lancement

**Avant**

- [ ] `ffmpeg -version` et `ffprobe -version` répondent (sinon : erreurs de décodage sur tous les clips).
- [ ] L'environnement virtuel est activé et `pip install -r requirements.txt` est passé.
- [ ] Vous avez de la place sur le disque.

**Après**

- [ ] La dernière ligne indique `Done. N/N clips downloaded successfully`. Les échecs sont listés un par un (`Failed to download ...`), ils ne bloquent pas le reste.
- [ ] Aucun message `WARNING: found 0 quotes for <race>`. S'il apparaît, la page n'a pas pu être lue (voir la section suivante).
- [ ] Les 4 fichiers JSON existent et le dossier `MP3/` contient un sous-dossier par race.
- [ ] Aucune entrée avec `"name": null` dans les JSON : ce serait le signe que le wiki a changé la structure de ses titres de sections.

## Particularités à connaître

- **Cloudflare** : le wiki est protégé par un challenge JavaScript. Avec `requests` seul, il renvoie une page « Just a moment... » (HTTP 403) sans lever d'erreur, et le script ne trouverait aucune réplique. Le projet utilise donc `cloudscraper`. Ne le remplacez pas par `requests`.
- **Protection des données existantes** : si une race ne renvoie aucune réplique (page bloquée ou mise en page modifiée), elle est **ignorée** : son dossier `MP3/<Race>/` et son JSON ne sont pas touchés. Pour une race qui a réussi, `MP3/<Race>/` est **supprimé puis retéléchargé** à chaque lancement : ne placez rien d'autre dedans.
- **Faux mp3** : les fichiers sources sont en réalité des `.ogg`. Le script laisse `ffmpeg` détecter le format à la lecture et n'impose `mp3` qu'à l'export. Forcer `format="mp3"` en entrée fait échouer tous les décodages.
- **Deux variantes de titres** : le wiki sert au hasard deux structures de titres de sections (`<span class="mw-headline">` ou `<h2 id=...>`). `parse_race_page()` gère les deux.

## Configuration

| Réglage | Où | Défaut |
|---|---|---|
| Téléchargements simultanés | `MAX_WORKERS` dans `scrapping.py` | `8` |
| Pages / races scrapées | liste `urls` dans `main()` | 4 races |

## Ce qui n'est pas versionné

`env/`, `MP3/` et les `*.json` générés sont exclus par le `.gitignore`. Lancez le script pour les recréer.

## Crédits et droits

- Répliques et sons : © Blizzard Entertainment, contenu du Wiki WoW (Fandom) sous licence CC BY-SA. Ce dépôt ne contient aucun fichier audio.
- Image : *Orc grunt* par Lucas Salcedo, [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/), via [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Orc_grunt_by_Lucas_Salcedo_(cropped).jpg).
- Projet non officiel, sans lien avec Blizzard Entertainment.
