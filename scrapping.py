
import io
import os
import shutil
import string
import json
import time
import concurrent.futures

import cloudscraper
from bs4 import BeautifulSoup
from pydub import AudioSegment


def clear_name(name) -> str:
    # Only lower case
    ret = name.lower()

    # Keep only alphacharacter and punctuations
    ret = ''.join(letter if letter.isalpha() or letter in '!?.' else "_" for letter in ret)

    # Delete useless tag
    ret = ret.replace("__br__", "").replace("<br/>", "")
    ret = ret.replace("_br__", "").replace("___", "")

    return ret


def write_mp3(session, url, folder_name, file_name):
    # Download the clip straight into memory
    get_data = session.get(url)
    # Source clips are actually .ogg despite the ".mp3" naming convention we
    # save them under - let ffmpeg auto-detect the real container instead of
    # forcing "mp3" (which fails to decode).
    sound = AudioSegment.from_file(io.BytesIO(get_data.content))

    # Create the folder if needed (safe to call from multiple threads)
    os.makedirs(folder_name, exist_ok=True)

    sound.export(folder_name + file_name + ".mp3", format="mp3")


def parse_race_page(soup):
    """Yield (audio_url, quote_text, unit_name) for every quote <li> on the page,
    tracking the nearest preceding section heading in a single linear pass.

    The wiki renders section headers in two different ways depending on the
    page variant served: most sections use <span class="mw-headline" id=...>,
    but some (e.g. the "Alertes" table) use a collapsible-widget <h2 id=...>
    with no inner mw-headline span. Both are treated as heading markers.
    """
    current_name = None
    for tag in soup.find_all(['span', 'h2', 'h3', 'h4', 'li']):
        if tag.name == 'span':
            if 'mw-headline' in (tag.get('class') or []):
                current_name = tag.get('id')
            continue

        if tag.name in ('h2', 'h3', 'h4'):
            if tag.get('id'):
                current_name = tag.get('id')
            continue

        is_audio = tag.find('audio')
        if not is_audio:
            continue

        audio_url = is_audio.get('src')
        is_audio.extract()
        quote_text = tag.get_text()

        yield audio_url, quote_text, current_name


MAX_WORKERS = 8  # benchmarked against the live site: diminishing returns past ~8 concurrent downloads


def main():
    start_time = time.time()
    urls = (
        ["https://wowwiki.fandom.com/fr/wiki/R%C3%A9pliques_de_Warcraft_III/Humain", "Humain"],
        ["https://wowwiki.fandom.com/fr/wiki/R%C3%A9pliques_de_Warcraft_III/Orc", "Orc"],
        ["https://wowwiki.fandom.com/fr/wiki/R%C3%A9pliques_de_Warcraft_III/Elfe_de_la_nuit", "Elfe_de_la_nuit"],
        ["https://wowwiki.fandom.com/fr/wiki/R%C3%A9pliques_de_Warcraft_III/Mort-vivant", "Mort-vivant"]
    )

    # wowwiki.fandom.com sits behind a Cloudflare JS challenge that plain
    # requests.Session() can't pass (gets a 403 "Just a moment..." page),
    # so use cloudscraper instead.
    session = cloudscraper.create_scraper()

    download_tasks = []
    id_g = 0
    for url, race_name in urls:
        json_data = {}
        id = 0

        get_page = session.get(url)
        soup = BeautifulSoup(get_page.content, "lxml")

        race_download_tasks = []
        for audio_url, quote_text, unit_name in parse_race_page(soup):
            get_replique = clear_name(quote_text)

            data = {
                "id_g": id_g,
                "id": id,
                "race": race_name,
                "replique": get_replique,
                "url": audio_url,
                "name": unit_name,
            }

            # Delete full punctuation for file name
            file_name = get_replique.translate(str.maketrans('', '', string.punctuation))
            data['file_name'] = file_name

            name = str(id_g) + "-" + file_name[:20]
            race_download_tasks.append((audio_url, f"./MP3/{race_name}/{unit_name}/", name))

            json_data[f"{id}-{data['name']}"] = data

            id += 1
            id_g += 1

        if not json_data:
            # Nothing scraped for this race (e.g. the page fetch was blocked or
            # its layout changed) - never overwrite existing JSON/MP3s with an
            # empty result.
            print(f"WARNING: found 0 quotes for {race_name}, leaving its JSON/MP3s untouched.")
            continue

        # Clean slate for this race: wipe previously downloaded clips before
        # redownloading, only now that we know the scrape actually succeeded.
        race_folder = f"./MP3/{race_name}"
        if os.path.exists(race_folder):
            shutil.rmtree(race_folder)

        download_tasks.extend(race_download_tasks)

        # Save json
        with open(f"{race_name}.json", "w") as file:
            json.dump(json_data, file, indent=4, ensure_ascii=False)

    scrape_elapsed = time.time() - start_time
    print(f"Scraped {len(download_tasks)} quotes in {scrape_elapsed:.1f}s, downloading audio "
          f"({MAX_WORKERS} at a time)...")

    total = len(download_tasks)
    completed = 0
    failures = 0
    download_start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(write_mp3, session, url, folder, name): (url, folder, name)
            for url, folder, name in download_tasks
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


if __name__ == "__main__":
    main()
