import os.path
import requests as rq

session = rq.session()

"""
Script handles the downloading and only the downloading of the files. 
No compression takes place

Also you provide the arguments interactively to the script and don't have to modify the script itself.

The script is single threaded and not optimized in any way shape or form.
"""


def target_loader(url: str, path: str):
    print(f"downloading {url}\n"
          f"to {path}")
    stream = rq.get(maxq_url["url"], headers={"user-agent": "Firefox"})
    if stream.ok:
        with open(path, "wb") as file:
            file.write(stream.content)

        print(f"Done {os.path.join(folder, f'{date}.mp4')}")


# provide login information
username = ""
password = ""
urls = []
url = ""
download_directory = ""

to_download = []

# login
while not username:
    username = input("please provide your username\n")

while not password:
    password = input(f"please provide the password for {username}\n")

while url != "n":
    if url and url != "p":
        urls.append(url)
    if url == "p":
        for u in urls:
            print(u)

    url = input("if you have another url, please enter it,\n"
                "to print the currently selected urls enter 'p',\n"
                "otherwise enter 'n'\n")

while not download_directory:
    download_directory = input("Please provide a target where you would like to download to\n")

# get login
login = session.post(url="https://video.ethz.ch/j_security_check",
                     headers={"user-agent": "lol herre"}, data={"_charset_": "utf-8", "j_username": username,
                                                                "j_password": password,
                                                                "j_validate": True})

cookies = login.cookies

if login.status_code == 403:
    print("Wrong Credentials")

for u in urls:
    # load all episodes
    episodes = session.get(u.replace(".html", ".series-metadata.json"), headers={"user-agent": "lol it still worked"})
    ep = episodes.json()

    all_episodes = ep["episodes"]

    folder = u.split("/")[-1]
    folder = folder.replace(".html", "")
    folder = os.path.join(download_directory, folder)

    # create local target folder
    if not os.path.exists(folder):
        os.makedirs(folder)

    # get streams from episodes:
    for ep in all_episodes:
        eid = ep["id"]
        target = u.replace(".html", f"/{eid}.series-metadata.json")
        episode = session.get(target,
                              headers={"user-agent": "lol it still workd"}, cookies=cookies)

        # episode downloaded correctly
        if episode.ok:
            # get metadata from json
            j = episode.json()
            maxq_url = j["selectedEpisode"]["media"]["presentations"][0]
            date = j["selectedEpisode"]["createdAt"]

            if not os.path.exists(os.path.join(folder, f"{date}.mp4")):
                # to_download.append({"url": maxq_url["url"], "path": os.path.join(folder, f"{date}.mp4")})
                print(f"downloading {maxq_url['url']}\n"
                      f"to {os.path.join(folder, f'{date}.mp')}")

                stream = rq.get(maxq_url["url"], headers={"user-agent": "Firefox"})
                if stream.ok:
                    with open(os.path.join(folder, f"{date}.mp4"), "wb") as file:
                        file.write(stream.content)

                    print(f"Done {os.path.join(folder, f'{date}.mp4')}")

        else:
            print(episode.status_code)

print("all done")
