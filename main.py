import json
import re

import requests

from bs4 import BeautifulSoup


def write_mp3(url, file_name):
    # # Get url of the mp3
    get_data = requests.get(url)

    # Save mp3
    with open(file_name + ".mp3", "wb") as f:
        f.write(get_data.content)



def main():
    w3_urls_dct = {
        "Humain": "https://wowwiki.fandom.com/fr/wiki/R%C3%A9pliques_de_Warcraft_III/Humain",
        "Orc": "https://wowwiki.fandom.com/fr/wiki/R%C3%A9pliques_de_Warcraft_III/Orc", 
        "Elfe de la nuit": "https://wowwiki.fandom.com/fr/wiki/R%C3%A9pliques_de_Warcraft_III/Elfe_de_la_nuit",
        "Mort-vivant": "https://wowwiki.fandom.com/fr/wiki/R%C3%A9pliques_de_Warcraft_III/Mort-vivant"
    }

    id_global = 1
    for key, value in w3_urls_dct.items():
        data_dct_w3 = {}
        get_page = requests.get(value)
        soup = BeautifulSoup(get_page.content, "html.parser")

        # First get all Units name as KEYS
        mydivs = soup.find_all("span", {"class": "mw-headline"})
        for val in enumerate(mydivs):
            if "(beta)" in val[1].text:
                pass
            else:
                result = re.sub(r'\s*\([^)]*\)', '',  val[1].text)
                data_dct_w3[result] = {}
        
        id = 1
        # Get last key of dict to check changes
        last_key = list(data_dct_w3.keys())[0]

        for li in soup.find_all("li"):
            has_audio = li.find("audio")
            
            if has_audio:
                name = li.find_previous("span",  class_="mw-headline")

                if "beta" not in name.text:
                    data = {}
                    data["id_g"] = id_global
                    data["id"] = id
                    data["race"] = key
                    
                    result = re.sub(r'\s*\([^)]*\)', '',  name.text)
                    data["name"] = result

                    data["replique"] = str(li.contents[1][2:])
                    
                    data["url"] = has_audio.get("src")
                    write_mp3(data["url"], f"./MP3/{id_global}")

                    id_global += 1
                    id += 1  

                    if last_key != data["name"]:
                        id = len(data_dct_w3[data["name"]]) + 1
                        data["id"] = id

                    data_dct_w3[data["name"]][id] = data

        with open(f"{key}.json", "w") as file:
            json.dump(data_dct_w3, file, indent=4, ensure_ascii=False)


if __name__ == "__main__":
    print("Getting data...")
    main()
    print("Done =)")