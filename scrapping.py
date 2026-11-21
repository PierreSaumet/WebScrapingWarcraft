import argparse
import concurrent.futures
import io
import json
import os
import random
import re
import shutil
import string
import time

import cloudscraper
import requests
from bs4 import BeautifulSoup
from pydub import AudioSegment

MAX_WORKERS = 8  # benchmarked against the live site: diminishing returns past ~8 concurrent downloads
HERE = os.path.dirname(os.path.abspath(__file__))
UNIT_NAMES_FILE = os.path.join(HERE, "unit_names.json")
EN_API = "https://warcraft.wiki.gg/api.php"
EN_USER_AGENT = "WebScrapingWarcraft/1.0 (educational scraper)"

# Canonical race names are shared by every language; the third item is the
# page reference handed to the language's fetcher (FR: URL, EN: wiki page title).
SOURCES = {
    "fr": [
        ("Human", "https://wowwiki.fandom.com/fr/wiki/R%C3%A9pliques_de_Warcraft_III/Humain"),
        ("Orc", "https://wowwiki.fandom.com/fr/wiki/R%C3%A9pliques_de_Warcraft_III/Orc"),
        ("Night_Elf", "https://wowwiki.fandom.com/fr/wiki/R%C3%A9pliques_de_Warcraft_III/Elfe_de_la_nuit"),
        ("Undead", "https://wowwiki.fandom.com/fr/wiki/R%C3%A9pliques_de_Warcraft_III/Mort-vivant"),
    ],
    "en": [
        ("Human", "Quotes_of_Warcraft_III/Human_Alliance"),
        ("Orc", "Quotes_of_Warcraft_III/Orc_Horde"),
        ("Night_Elf", "Quotes_of_Warcraft_III/Night_Elf_Sentinels"),
        ("Undead", "Quotes_of_Warcraft_III/Undead_Scourge"),
    ],
}

# <li> only on the FR wiki; the EN wiki also puts some quotes (Ready/Warcry) in <dd>.
QUOTE_TAGS = {"fr": ("li",), "en": ("li", "dd")}


def clear_name(name) -> str:
    # Only lower case
    ret = name.lower()

    # Keep only alphacharacter and punctuations
    ret = ''.join(letter if letter.isalpha() or letter in '!?.' else "_" for letter in ret)

    # Delete useless tag
    ret = ret.replace("__br__", "").replace("<br/>", "")
    ret = ret.replace("_br__", "").replace("___", "")

    return ret


def safe_dirname(name) -> str:
    """Filesystem-safe folder name (e.g. 'Peasant/Militia' must not nest folders)."""
    if not name:
        return "Unknown"
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)


DOWNLOAD_RETRIES = 4


def is_transient(exc):
    """Worth retrying: timeouts, connection errors, Cloudflare challenges, 403/429/5xx.
    Other 4xx (404, 410...) are permanent: fail fast."""
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        code = exc.response.status_code
        return code in (403, 429) or code >= 500
    return True


def download_with_retry(session, url, retries=DOWNLOAD_RETRIES):
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=60)
            resp.raise_for_status()
            return resp.content
        except (requests.RequestException, cloudscraper.exceptions.CloudflareException) as exc:
            if attempt == retries - 1 or not is_transient(exc):
                raise
            time.sleep(2 ** attempt + random.random())  # 1s, 2s, 4s (+ jitter)


def write_mp3(session, url, folder_name, file_name):
    # Download the clip straight into memory. The CDN sometimes answers a
    # transient 403/429/5xx under load, so retry the download (not the decode).
    content = download_with_retry(session, url)
    # Source clips are .ogg (FR) or .wav (EN) despite the ".mp3" naming
    # convention we save them under - let ffmpeg auto-detect the real container
    # instead of forcing "mp3" (which fails to decode).
    sound = AudioSegment.from_file(io.BytesIO(content))

    # Create the folder if needed (safe to call from multiple threads)
    os.makedirs(folder_name, exist_ok=True)

    sound.export(folder_name + file_name + ".mp3", format="mp3")


def parse_race_page(soup, quote_tags=("li",)):
    """Yield (audio_url, quote_text, unit_name) for every quote on the page,
    tracking the nearest preceding section heading in a single linear pass.

    The wiki renders section headers in two different ways depending on the
    page variant served: most sections use <span class="mw-headline" id=...>,
    but some (e.g. the FR "Alertes" table) use a collapsible-widget <h2 id=...>
    with no inner mw-headline span. Both are treated as heading markers.
    """
    current_name = None
    for tag in soup.find_all(['span', 'h2', 'h3', 'h4', *quote_tags]):
        if tag.name == 'span':
            if 'mw-headline' in (tag.get('class') or []):
                current_name = tag.get('id')
            continue

        if tag.name in ('h2', 'h3', 'h4'):
            if tag.get('id'):
                current_name = tag.get('id')
            continue

        # Only this tag's own clips: a nested <li>/<dd> keeps its own audio and text.
        audios = [a for a in tag.find_all('audio') if a.find_parent(list(quote_tags)) is tag]
        if not audios:
            continue

        # FR serves the audio URL in `src` or, with lazy loading, `data-src`;
        # EN (MediaWiki audio button) nests it in <audio><source src=...>.
        # A quote can carry several clips (EN: two voice variants, "Link/Link").
        audio_urls = []
        for audio in audios:
            source = audio.find('source')
            audio_urls.append(audio.get('src') or audio.get('data-src')
                              or (source.get('src') if source else None))
            # EN wraps <audio> + play button in a <span>; drop it whole so no
            # "Link"/play glyph leaks into the quote text.
            wrapper = audio.parent
            if wrapper is not tag and wrapper.name == 'span' and wrapper.find('a', class_='ext-audiobutton'):
                wrapper.extract()
            else:
                audio.extract()
        for nested in tag.find_all(list(quote_tags)):
            nested.extract()  # still iterated later by the outer loop, with its own audio and text
        quote_text = tag.get_text()
        if len(audios) > 1:
            quote_text = re.sub(r'(\s*/\s*)+$', '', quote_text)

        for audio_url in audio_urls:
            if audio_url:
                yield audio_url, quote_text, current_name


def fetch_html_fr(session, url, retries=3):
    last_exc = None
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=60)
            resp.raise_for_status()  # a blocked fetch must be visible, not parsed as "0 quotes"
            return resp.content
        except Exception as exc:
            last_exc = exc
            time.sleep(1.5 * (attempt + 1))
    raise last_exc


def fetch_html_en(session, page, retries=3):
    params = dict(action="parse", page=page, prop="text", format="json", formatversion=2)
    last_exc = None
    for attempt in range(retries):
        try:
            resp = session.get(EN_API, params=params, timeout=60)
            resp.raise_for_status()
            return resp.json()["parse"]["text"]
        except Exception as exc:  # network error, 403, malformed json...
            last_exc = exc
            time.sleep(1.5 * (attempt + 1))
    raise last_exc


def make_sessions(langs):
    sessions = {}
    if "fr" in langs:
        # wowwiki.fandom.com sits behind a Cloudflare JS challenge that plain
        # requests can't pass (403 "Just a moment..."), so use cloudscraper.
        sessions["fr"] = cloudscraper.create_scraper()
    if "en" in langs:
        # warcraft.wiki.gg rejects cloudscraper and browser-like UAs on HTML
        # pages, but its MediaWiki API answers plain requests with a descriptive UA.
        s = requests.Session()
        s.headers["User-Agent"] = EN_USER_AGENT
        sessions["en"] = s
    return sessions


def fetch_all_pages(langs, sessions):
    """Fetch every (lang, race) page concurrently. Returns {(lang, race): html or None}.
    FR stays sequential (cloudscraper session isn't meant for concurrent challenge solving)."""
    def fetch(lang, race, ref):
        try:
            if lang == "fr":
                return fetch_html_fr(sessions["fr"], ref)
            return fetch_html_en(sessions["en"], ref)
        except Exception as exc:
            print(f"WARNING: could not fetch {lang}/{race}: {exc}")
            return None

    pages = {}

    def fetch_fr():
        for race, ref in SOURCES["fr"]:
            pages[("fr", race)] = fetch("fr", race, ref)

    def fetch_en(race, ref):
        pages[("en", race)] = fetch("en", race, ref)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        futures = []
        if "fr" in langs:
            futures.append(ex.submit(fetch_fr))
        if "en" in langs:
            for race, ref in SOURCES["en"]:
                futures.append(ex.submit(fetch_en, race, ref))
        for f in futures:
            f.result()
    return pages


def load_unit_table():
    try:
        with open(UNIT_NAMES_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


def build_unit_index(table):
    """Return {(lang, race): {unit_name: unit_key}} from unit_names.json."""
    index = {}
    for race, units in table.items():
        for key, names in units.items():
            for lang in ("fr", "en"):
                value = names.get(lang)  # one name, or a list (e.g. a unit's several forms)
                for name in ([value] if isinstance(value, str) else value or []):
                    index.setdefault((lang, race), {})[name] = key
    return index


def fallback_keys(race_counts, race_table):
    """Units whose EN clips are completed with the FR ones: no EN clip at all, or
    flagged `"fallback_fr": true` in unit_names.json (EN wiki has too few, e.g. Kodo Beast)."""
    keys = set()
    for key, names in race_table.items():
        n = race_counts.get(key, {})
        if n.get("fr", 0) > 0 and (n.get("en", 0) == 0 or names.get("fallback_fr")):
            keys.add(key)
    return keys


def display_name(names, key):
    """Folder/section name used for an unit in EN: its EN name, else its FR name."""
    value = names.get("en") or names.get("fr") or key
    return value if isinstance(value, str) else value[0]


def comparison_rows(counts, langs):
    """{race: [row]} with per-unit clip counts: fr, en (as on the wikis), en_after (EN after the FR fallback)."""
    table = load_unit_table()
    both = "fr" in langs and "en" in langs
    result = {}
    for race in [r for r, _ in SOURCES["fr"]]:
        units = counts.get(race, {})
        race_table = table.get(race, {})
        filled = fallback_keys(units, race_table) if both else set()
        rows = []
        for key in sorted(set(units) | set(race_table)):
            n = units.get(key, {})
            fr, en = n.get("fr", 0), n.get("en", 0)
            names = race_table.get(key, {})
            label = display_name(names, key) if names else key.lstrip("?")
            if not n:
                status = "stale"
            elif not both:
                status = ""
            elif en == 0:
                status = "FR only"
            elif fr == 0:
                status = "EN only"
            else:
                status = "ok" if fr == en else "count differs"
            rows.append({"key": key, "label": label, "fr": fr, "en": en,
                         "en_after": en + fr if key in filled else en, "filled": key in filled, "status": status})
        result[race] = sorted(rows, key=lambda r: r["label"].lower())
    return result


def print_comparison(counts, langs):
    """Full per race / per unit table (--check-names)."""
    both = "fr" in langs and "en" in langs
    for race, rows in comparison_rows(counts, langs).items():
        print(f"\n== {race} ==")
        head = f"{'unit':38} " + " ".join(f"{lang.upper():>5}" for lang in langs)
        print(head + ("   diff  EN+FB  status" if both else ""))
        for r in rows:
            if r["status"] == "stale":
                print(f"{r['label'][:38]:38} (in unit_names.json but not scraped: stale or typo?)")
                continue
            line = f"{r['label'][:38]:38} " + " ".join(f"{r[lang]:5}" for lang in langs)
            if both:
                line += f"  {r['fr'] - r['en']:+5}  {r['en_after']:5}  {r['status']}"
            print(line)
    print_summary(counts, langs)


def print_summary(counts, langs, top=5):
    """Compact end-of-run overview: totals per race and the biggest FR/EN gaps."""
    if not ("fr" in langs and "en" in langs):
        return
    rows_by_race = comparison_rows(counts, langs)
    print("\n=== FR / EN summary (clips) ===")
    print(f"{'race':10} {'FR':>6} {'EN wiki':>8} {'EN +FR fallback':>16} {'units ok':>9} {'differ':>7} {'one side':>9}")
    tot = [0, 0, 0]
    for race, rows in rows_by_race.items():
        fr = sum(r["fr"] for r in rows); en = sum(r["en"] for r in rows); after = sum(r["en_after"] for r in rows)
        ok = sum(r["status"] == "ok" for r in rows)
        differ = sum(r["status"] == "count differs" for r in rows)
        one = sum(r["status"] in ("FR only", "EN only") for r in rows)
        tot = [tot[0] + fr, tot[1] + en, tot[2] + after]
        print(f"{race:10} {fr:6} {en:8} {after:16} {ok:9} {differ:7} {one:9}")
    print(f"{'TOTAL':10} {tot[0]:6} {tot[1]:8} {tot[2]:16}")
    print(f"\nLargest FR/EN gaps (wiki counts, before fallback; full table: python scrapping.py --check-names):")
    for race, rows in rows_by_race.items():
        gaps = sorted((r for r in rows if r["status"] in ("count differs", "FR only", "EN only")),
                      key=lambda r: -abs(r["fr"] - r["en"]))[:top]
        print(f"  {race}: " + ", ".join(f"{r['label']} {r['fr']}/{r['en']}" + ("*" if r["filled"] else "") for r in gaps))
    print("  (FR/EN clips; * = EN completed with FR clips)")


def write_all_quotes(path="data/all_quotes.json"):
    """Merge every data/<lang>/<Race>.json found on disk into one file:
    race -> unit_key -> {names, fr: [...], en: [...]}. Reads the files (not memory)
    so a --fr or --en run still produces a complete recap from the other language's last run."""
    table = load_unit_table()
    merged = {}
    missing = 0
    for race, _ref in SOURCES["fr"]:
        units = {}
        for lang in ("fr", "en"):
            try:
                with open(f"data/{lang}/{race}.json", encoding="utf-8") as fh:
                    records = json.load(fh)
            except FileNotFoundError:
                continue
            for rec in records.values():
                key = rec.get("unit_key") or f"?{rec.get('name')}"
                unit = units.setdefault(key, {"names": {"fr": None, "en": None}, "fr": [], "en": []})
                names = table.get(race, {}).get(key)
                if names:
                    unit["names"] = {"fr": names.get("fr"), "en": names.get("en")}
                file = f"MP3/{lang}/{race}/{safe_dirname(rec['name'])}/{rec['id_g']}-{rec['file_name'][:20]}.mp3"
                if not os.path.exists(file):
                    missing += 1  # download failed (or stale JSON): don't advertise a missing file
                    continue
                unit[lang].append({
                    "id_g": rec["id_g"], "id": rec["id"], "replique": rec["replique"], "url": rec["url"],
                    "name": rec["name"], "fallback_from": rec.get("fallback_from"),
                    "file": file,
                })
        if units:
            merged[race] = dict(sorted(units.items()))
    if not merged:
        return
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2, ensure_ascii=False)
    print(f"Recap written to {path} ({sum(len(u['fr']) + len(u['en']) for r in merged.values() for u in r.values())} quotes)"
          + (f", {missing} skipped (mp3 missing)." if missing else "."))


def main():
    parser = argparse.ArgumentParser(description="Scrape Warcraft III voice lines (FR and/or EN).")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="scrape FR and EN (default)")
    group.add_argument("--fr", "-f", action="store_true", help="scrape French quotes only")
    group.add_argument("--en", "-e", action="store_true", help="scrape English quotes only")
    parser.add_argument("--check-names", action="store_true",
                        help="scrape pages only and list unit names missing from unit_names.json (no download)")
    args = parser.parse_args()
    langs = ["fr"] if args.fr else ["en"] if args.en else ["fr", "en"]
    # EN is completed with FR clips for units the EN wiki lacks, so FR pages are
    # always scraped when EN is requested (but only written if FR was requested).
    scrape_langs = ["fr", "en"] if "en" in langs else ["fr"]
    if args.check_names:
        scrape_langs = ["fr", "en"] if "en" in langs else langs

    start_time = time.time()
    sessions = make_sessions(scrape_langs)
    pages = fetch_all_pages(scrape_langs, sessions)
    unit_table = load_unit_table()
    unit_index = build_unit_index(unit_table)

    download_tasks = []  # (lang, url, folder, name)
    unmatched = {}
    counts = {}  # race -> unit_key (or '?name') -> lang -> number of clips
    fr_quotes = {}  # race -> [(url, replique, unit_name, unit_key)], source of the EN fallback
    for lang in scrape_langs:
        id_g = 0
        for race, _ref in SOURCES[lang]:
            html = pages.get((lang, race))
            quotes = list(parse_race_page(BeautifulSoup(html, "lxml"), QUOTE_TAGS[lang])) if html else []

            json_data = {}
            race_download_tasks = []
            names = unit_index.get((lang, race), {})
            id = 0
            for audio_url, quote_text, unit_name in quotes:
                get_replique = clear_name(quote_text)
                unit_key = names.get(unit_name)
                if unit_key is None and names:
                    unmatched.setdefault((lang, race), set()).add(unit_name)

                bucket = counts.setdefault(race, {}).setdefault(unit_key or f"?{unit_name}", {})
                bucket[lang] = bucket.get(lang, 0) + 1
                if lang == "fr":
                    fr_quotes.setdefault(race, []).append((audio_url, get_replique, unit_name, unit_key))

                data = {
                    "id_g": id_g,
                    "id": id,
                    "lang": lang,
                    "race": race,
                    "replique": get_replique,
                    "url": audio_url,
                    "name": unit_name,
                    "unit_key": unit_key,
                    "fallback_from": None,
                }

                # Delete full punctuation for file name
                file_name = get_replique.translate(str.maketrans('', '', string.punctuation))
                data['file_name'] = file_name

                name = str(id_g) + "-" + file_name[:20]
                folder = f"./MP3/{lang}/{race}/{safe_dirname(unit_name)}/"
                race_download_tasks.append((lang, audio_url, folder, name))

                json_data[f"{id}-{data['name']}"] = data

                id += 1
                id_g += 1

            if lang == "en" and json_data and not args.check_names:
                # Complete units the EN wiki lacks with the FR clips (marked fallback_from="fr").
                race_table = unit_table.get(race, {})
                for key in sorted(fallback_keys(counts.get(race, {}), race_table)):
                    unit_name = display_name(race_table[key], key)
                    for audio_url, replique, _fr_name, fr_key in fr_quotes.get(race, []):
                        if fr_key != key:
                            continue
                        file_name = replique.translate(str.maketrans('', '', string.punctuation))
                        json_data[f"{id}-{unit_name}"] = {
                            "id_g": id_g, "id": id, "lang": lang, "race": race,
                            "replique": replique, "url": audio_url, "name": unit_name,
                            "unit_key": key, "fallback_from": "fr", "file_name": file_name,
                        }
                        folder = f"./MP3/{lang}/{race}/{safe_dirname(unit_name)}/"
                        race_download_tasks.append(("fr", audio_url, folder, f"{id_g}-{file_name[:20]}"))
                        id += 1
                        id_g += 1

            if not json_data:
                # Nothing scraped for this race (e.g. the page fetch was blocked or
                # its layout changed) - never overwrite existing JSON/MP3s with an
                # empty result.
                print(f"WARNING: found 0 quotes for {lang}/{race}, leaving its JSON/MP3s untouched.")
                continue

            if args.check_names or lang not in langs:
                continue

            if lang == "en" and not fr_quotes.get(race):
                # The EN dataset is completed with FR clips: if the FR source is empty
                # (blocked fetch / layout change), rewriting would silently drop them.
                print(f"WARNING: no FR quotes for {race} (needed for the EN fallback), "
                      f"leaving en/{race} JSON/MP3s untouched.")
                continue

            # Clean slate for this lang/race: wipe previously downloaded clips before
            # redownloading, only now that we know the scrape actually succeeded.
            race_folder = f"./MP3/{lang}/{race}"
            if os.path.exists(race_folder):
                shutil.rmtree(race_folder)

            download_tasks.extend(race_download_tasks)

            # Save json
            os.makedirs(f"data/{lang}", exist_ok=True)
            with open(f"data/{lang}/{race}.json", "w", encoding="utf-8") as file:
                json.dump(json_data, file, indent=4, ensure_ascii=False)

    if not unit_index:
        print("NOTE: unit_names.json not found or empty, unit_key left null.")
    for (lang, race), missing in sorted(unmatched.items()):
        print(f"UNMAPPED {lang}/{race} ({len(missing)}): {', '.join(sorted(map(str, missing)))}")

    if args.check_names:
        print_comparison(counts, scrape_langs)
        return

    scrape_elapsed = time.time() - start_time
    print(f"Scraped {len(download_tasks)} quotes in {scrape_elapsed:.1f}s, downloading audio "
          f"({MAX_WORKERS} at a time)...")

    total = len(download_tasks)
    completed = 0
    failures = 0
    download_start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(write_mp3, sessions[lang], url, folder, name): (url, folder, name)
            for lang, url, folder, name in download_tasks
        }
        for future in concurrent.futures.as_completed(futures):
            completed += 1
            try:
                future.result()
            except Exception as exc:
                failures += 1
                url, folder, name = futures[future]
                print(f"\nFailed to download {folder}{name}.mp3 ({url}): {exc}")

            elapsed = time.time() - download_start
            pct = completed / total * 100
            eta = (elapsed / completed) * (total - completed) if completed else 0
            print(f"\r[{completed}/{total}] {pct:5.1f}%  elapsed {elapsed:6.1f}s  eta {eta:6.1f}s",
                  end="", flush=True)

    print()
    total_elapsed = time.time() - start_time
    print(f"Done. {total - failures}/{total} clips downloaded successfully in {total_elapsed:.1f}s.")
    print_summary(counts, scrape_langs)
    write_all_quotes()


if __name__ == "__main__":
    main()
