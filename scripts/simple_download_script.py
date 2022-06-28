import os.path
import time

import requests as rq
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
session = rq.session()


@dataclass
class SeriesLogin:
    """
    Url needs to be a match for a series like: https://videos.ethz.ch/lectures/d-infk/2022/spring/NUMBER, no .html or
    .series-metadata. It may also be a specific episode of a series.
    """
    url: str
    username: str = None
    password: str = None


def target_loader(command: dict):
    url = command["url"]
    path = command["path"]
    print(f"downloading {url}\n"
          f"to {path}")
    stream = rq.get(maxq_url["url"], headers={"user-agent": "Firefox"})
    if stream.ok:
        with open(path, "wb") as file:
            file.write(stream.content)

        print(f"Done {os.path.join(folder, f'{date}.mp4')}")
        return "success"


# provide login information
username = "uname"
password = "pw"
urls = [SeriesLogin("https://video.ethz.ch/lectures/d-math/2022/spring/401-0212-16L.html"),
        SeriesLogin("https://video.ethz.ch/lectures/d-infk/2022/spring/252-0029-00L.html"),
        SeriesLogin("https://video.ethz.ch/lectures/d-infk/2022/spring/252-0028-00L.html")]

download_directory = "download folder"

to_download = []


# get login
login = session.post(url="https://video.ethz.ch/j_security_check",
                     headers={"user-agent": "lol herre"}, data={"_charset_": "utf-8", "j_username": username,
                                                                "j_password": password,
                                                                "j_validate": True})

cookies = login.cookies

if login.status_code == 403:
    print("Wrong Credentials")


for u in urls:
    if u.username is not None and u.password is not None:
        strip_url = u.url.replace("www.", "").replace(".html", "").replace(".series-metadata.json", "")
        login = rq.post(url=f"{strip_url}.series-login.json",
                        headers={"user-agent": "lol herre"},
                        data={"_charset_": "utf-8", "username": u.username, "password": u.password})

    # load all episodes
    episodes = session.get(u.url.replace(".html", ".series-metadata.json"), headers={"user-agent": "lol it still works"})
    ep = episodes.json()

    all_episodes = ep["episodes"]

    folder = u.url.split("/")[-1]
    folder = folder.replace(".html", "")
    folder = os.path.join(download_directory, folder)

    # create local target folder
    if not os.path.exists(folder):
        os.makedirs(folder)

    # get streams from episodes:
    for ep in all_episodes:
        eid = ep["id"]
        target = u.url.replace(".html", f"/{eid}.series-metadata.json")
        episode = session.get(target, headers={"user-agent": "lol it still worked"})

        # episode downloaded correctly
        if episode.ok:
            # get metadata from json
            j = episode.json()
            maxq_url = j["selectedEpisode"]["media"]["presentations"][0]
            date = j["selectedEpisode"]["createdAt"]

            if not os.path.exists(os.path.join(folder, f"{date}.mp4")):
                to_download.append({"url": maxq_url["url"], "path": os.path.join(folder, f"{date}.mp4")})

                # print(f"downloading {maxq_url['url']}\n"
                #       f"to {os.path.join(folder, f'{date}.mp')}")
                #
                # stream = rq.get(maxq_url["url"], headers={"user-agent": "Firefox"})
                # if stream.ok:
                #     with open(os.path.join(folder, f"{date}.mp4"), "wb") as file:
                #         file.write(stream.content)
                #
                #     print(f"Done {os.path.join(folder, f'{date}.mp4')}")

        else:
            print(episode.status_code)


tp = ThreadPoolExecutor(max_workers=5)
result = tp.map(target_loader, to_download)

for r in result:
    print(r)