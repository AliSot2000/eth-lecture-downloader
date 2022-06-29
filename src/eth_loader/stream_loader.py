import os
import traceback

import requests as rq
import multiprocessing as mp
import queue
import time
import pickle
from multiprocessing import Process
import json
from dataclasses import dataclass
from typing import List
from sqlite3 import *
import datetime


def get_stream(website_url: str, identifier: str, headers: dict, cookies: bytes, parent_id: int) -> dict:
    """
    Function to download a single metadata file for a given video_site and video entry. The website_url needs to be of type:

    /category/subcategory/year/season/lecture_id/long-id.series-metadata.json

    or:

    /category/subcategory/site.html

    The function **expects** to receive a valid lecture url. If an url is provided, that doesn't contain a video,
    it will try to download it anyway. The function shouldn't fail except if the site doesn't exist.

    :param cookies:
    :param website_url: url to download eg. /category/subcategory/year/season/lecture_id.html
    :param identifier: str for thread to give information where the download was executed in case of an error.
    :param headers: dict to be passed to the request library. Download will fail if no user-agent is provided.
    """

    url = website_url.replace("\n", "")
    cj = pickle.loads(cookies)

    result = rq.get(url=url, headers=headers, cookies=cj)
    content = None
    # https://www.asdf.com/path?args

    if result.ok:
        content = result.content.decode("utf-8")
    else:
        print(f"{identifier} error {result.status_code}")


    return {"url": url,  "status": result.status_code, "content": content, "parent_id": parent_id}


def handler(worker_nr: int, command_queue: mp.Queue, result_queue: mp.Queue):
    """
    Function executed in a worker thread. The function tries to download the given url in the queue. If the queue is
    empty for 20s, it will kill itself.

    :param worker_nr: Itendifier for debugging
    :param command_queue: Queue containing dictionaries containing all relevant information for downloading
    :param result_queue: Queue to put the results in. Handled in main thread.
    :return:
    """
    print("Starting")
    ctr = 0
    while ctr < 20:
        try:
            arguments = command_queue.get(block=False)
            ctr = 0
        except queue.Empty:
            ctr += 1
            time.sleep(1)
            continue

        result = get_stream(arguments["url"], str(worker_nr),
                            headers={"user-agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:100.0) "
                                                   "Gecko/20100101 Firefox/100.0"}, cookies=arguments["cookie-jar"],
                            parent_id=arguments["parent_id"])

        result_queue.put(result)
    print(f"{worker_nr} Terminated")


def folder_builder(root_folder: str) -> list:
    files = []
    sub_dirs = []

    dir_o_files = os.listdir(root_folder)

    for dof in dir_o_files:
        if os.path.isdir(os.path.join(root_folder, dof)):
            sub_dirs.append(os.path.join(root_folder, dof))
        elif os.path.isfile(os.path.join(root_folder, dof)):
            files.append(os.path.join(root_folder, dof))
        else:
            print(f"Couldn't assign {os.path.join(root_folder, dof)}")

    for subdir in sub_dirs:
        sub = folder_builder(subdir)
        files.extend(sub)

    return files


@dataclass
class SpecLogin:
    """
    Url needs to be a match for a series like: https://videos.ethz.ch/lectures/d-infk/2022/spring/NUMBER, no .html or
    .series-metadata. It may also be a specific episode of a series.
    """
    url: str
    username: str
    password: str


@dataclass
class EpisodeEntry:
    episode_url: str
    series_url: str
    parent_id: int


class BetterStreamLoader:
    def __init__(self, db: str, user_name: str = None, password: str = None,
                 spec_login: List[SpecLogin] = None):

        self.db_path = os.path.abspath(db)
        self.download_list = []

        self.sq_con = Connection(self.db_path)
        self.sq_cur = self.sq_con.cursor()

        self.verify_args_table()
        self.check_results_table()

        if spec_login is not None:
            self.specific_urls = [entry.url for entry in spec_login]
            self.specific_auth = spec_login
        else:
            self.specific_urls = []
            self.specific_auth = []

        # prepare urls for matching (removing file extension)
        for i in range(len(self.specific_urls)):
            # turn
            # /category/subcategory/year/season/lecture_id.series-metadata.json
            # or
            # /category/subcategory/year/season/lecture_id.html
            # into
            # /category/subcategory/year/season/lecture_id
            self.specific_urls[i] = self.specific_urls[i].replace(".html", "").replace(".series-metadata.json", "")

        self.workers = []

        self.result_queue = mp.Queue()
        self.command_queue = mp.Queue()
        self.nod = len(self.download_list)

        self.general_cookie = None
        self.login(user_name, password)

        # counters
        self.episode_insert_counter = 0
        self.episode_deprecated_counter = 0
        self.episode_active_counter = 0

        self.streams_insert_counter = 0
        self.streams_deprecated_counter = 0
        self.streams_active_counter = 0

    def get_episode_urls(self):
        self.verify_args_table()
        self.sq_cur.execute("SELECT key, json, URL FROM metadata WHERE deprecated = 0")

        row = self.sq_cur.fetchone()
        while row is not None:
            content = row[1]
            parent_id = row[0]
            parent_url = row[2]
            content_default = content.replace("''", "'")
            if "<!DOCTYPE html>" in content_default:
                print(f"Found an html site: {parent_url}")
                row = self.sq_cur.fetchone()
                continue

            try:
                result = json.loads(content_default)
            except json.JSONDecodeError:
                print(traceback.format_exc())
                print(content_default)
                print(parent_url)
                row = self.sq_cur.fetchone()
                continue

            result: dict
            if result.get("episodes") is not None:
                episodes = result.get("episodes")

                for ep in episodes:
                    ep_id = ep.get("id")

                    if ep_id is None:
                        print(f"Failed to find id with Content:\n{content_default}")
                        continue

                    # parent url without file extension
                    strip_url = parent_url.replace(".html", "").replace(".series-metadata.json", "")

                    # episode url with file extension
                    ep_url = f"{strip_url}/{ep_id}.series-metadata.json"

                    self.download_list.append(EpisodeEntry(parent_id=parent_id, series_url=parent_url, episode_url=ep_url))

            else:
                print(f"No episodes found {parent_url}")

            row = self.sq_cur.fetchone()

        self.nod = len(self.download_list)
        print(f"TODO: {self.nod}")
        time.sleep(10)

    def verify_args_table(self):
        self.sq_cur.execute("SELECT name FROM main.sqlite_master WHERE type='table' AND name='metadata'")

        if self.sq_cur.fetchone() is None:
            raise ValueError("didn't find the 'sites' table inside the given database.")

    def check_results_table(self):
        self.sq_cur.execute("SELECT name FROM main.sqlite_master WHERE type='table' AND name='episodes'")

        if self.sq_cur.fetchone() is None:
            self.sq_cur.execute("CREATE TABLE episodes "
                                "(key INTEGER PRIMARY KEY AUTOINCREMENT, "
                                "parent INTEGER, "
                                "URL TEXT , "
                                "json TEXT,"
                                "deprecated INTEGER DEFAULT 0 CHECK (episodes.deprecated >= 0 AND episodes.deprecated <= 1),"
                                "found TEXT,"
                                "streams TEXT)")

        self.sq_cur.execute("SELECT name FROM main.sqlite_master WHERE type='table' AND name='streams'")

        if self.sq_cur.fetchone() is None:
            self.sq_cur.execute("CREATE TABLE streams "
                                "(key INTEGER PRIMARY KEY AUTOINCREMENT, "
                                "URL TEXT , "
                                "resolution TEXT,"
                                "deprecated INTEGER DEFAULT 0 CHECK (deprecated >= 0 AND deprecated <= 1),"
                                "found TEXT)")

            self.sq_cur.execute("INSERT INTO streams (key, URL, resolution, found) VALUES (-1, 'dummy', 'dummy', 'dummy')")

    def spawn(self, threads: int = 100):
        """
        Spawns worker theads.

        :param threads: number of threads to spawn 1-10000
        :return:
        """
        if not 1 < threads < 10000:
            raise ValueError("Thread number outside supported range [1:10'000]")

        self.workers = []
        for i in range(threads):
            t = Process(target=handler, args=(i, self.command_queue, self.result_queue))
            t.start()
            self.workers.append(t)

        print("Workers Spawned")

    def initiator(self, workers: int = 100):
        self.reset_counters()
        self.get_episode_urls()
        self.spawn(workers)
        self.enqueue_job()
        self.dequeue_job()

        while self.workers_alive():
            time.sleep(30)
            print("Initiator Thread Sleeping Workers")

        self.cleanup()
        self.sq_con.commit()

        print("Statistics:")
        print("Episodes:")
        print(f"Inserted: {self.episode_insert_counter}, Updated: {self.episode_deprecated_counter}, "
              f"Active: {self.episode_active_counter}")
        print("Streams:")
        print(f"Inserted: {self.streams_insert_counter}, Updated: {self.streams_deprecated_counter}, "
              f"Active: {self.streams_active_counter}")

        self.deprecate_streams()
        self.sq_con.commit()
        print("DONE")

    def cleanup(self):
        """
        Waits for all worker processes to terminate and then joins them.
        :return:
        """
        counter = 0
        for worker in self.workers:
            worker: Process
            try:
                worker.join(10)
            except mp.TimeoutError:
                worker.kill()
            counter += 1
            print(f"Stopped {counter} threads")

    def workers_alive(self):
        """
        Function to verify that at least one of the workers hasn't exited.
        :return:
        """
        for worker in self.workers:
            worker: Process
            if worker.is_alive():
                return True

        return False

    def login(self, usr: str = None, pw: str = None):
        """
        Retrieves the login cookie to access LDAP restricted recordings.


        :param usr: ETH LDAP Username
        :param pw: ETH LDAP Password
        :return:
        """
        if pw is None or usr is None:
            print("No Credentials")
            return

        login = rq.post(url="https://video.ethz.ch/j_security_check",
                        headers={"user-agent": "lol herre"}, data={"_charset_": "utf-8", "j_username": usr,
                                                                   "j_password": pw,
                                                                   "j_validate": True})

        if login.ok:
            self.general_cookie = login.cookies

        elif login.status_code == 403:
            print("Wrong Credentials")

        else:
            print(login.status_code)
            print(vars(login))

    def spec_login(self, strip_url: str, usr: str, pw: str, other_cookies=None):
        """
        Provide the url as the series-metadata or html for the course site

        :param other_cookies:
        :param pw:
        :param usr:
        :param strip_url:
        :return:
        """
        strip_url = strip_url.replace("www.", "")
        login = rq.post(url=f"{strip_url}.series-login.json",
                        headers={"user-agent": "lol herre"},
                        data={"_charset_": "utf-8", "username": usr, "password": pw},
                        cookies=self.general_cookie)
        if login.ok:
            cj = login.cookies
            cj.update(self.general_cookie)

            if other_cookies is not None:
                cj.update(other_cookies)

            return cj
        else:
            print(login.status_code)
            print(vars(login))
            return self.general_cookie

    def enqueue_job(self):
        for dl in self.download_list:
            dl: EpisodeEntry
            cookie = self.general_cookie

            # url without file extension
            strip_url = dl.series_url.replace(".html", "").replace(".series-metadata.json", "")
            episode_striped_url = dl.episode_url.replace(".html", "").replace(".series-metadata.json", "")

            # if the stripped url is a specified url, get login of that url as well
            if strip_url in self.specific_urls:
                index = self.specific_urls.index(strip_url)

                cookie = self.spec_login(strip_url, self.specific_auth[index].username,
                                         self.specific_auth[index].password)

            # get specific login for specific episode if necessary
            if episode_striped_url in self.specific_urls:
                index = self.specific_urls.index(strip_url)

                cookie = self.spec_login(strip_url, self.specific_auth[index]["username"],
                                                 self.specific_auth[index]["password"], other_cookies=cookie)
            cookie_jar = pickle.dumps(cookie)

            print(f"Enqueueing: {dl.episode_url}")
            self.command_queue.put({"url": dl.episode_url, "cookie-jar": cookie_jar, "parent_id": dl.parent_id})

    def dequeue_job(self):
        ctr = 0
        download_counter = 0
        while ctr < 20:
            if not self.result_queue.empty():
                try:
                    res = self.result_queue.get()
                    if res["status"] == 200:
                        content = res["content"].replace("'", "''")

                        self.insert_update_episodes(parent_id=res["parent_id"], url=res["url"], json_str=content, raw_content=res["content"])
                        download_counter += 1
                        if download_counter % 100 == 0:
                            print(f"Downloaded so far {download_counter}")
                    else:
                        print(f"url {res['url']} with status code {res['status']}")
                        self.sq_con.commit()
                    ctr = 0
                except Exception as e:
                    print(traceback.format_exc())
                    print("\n\n\n FUCKING EXCEPTION \n\n\n")
            else:
                time.sleep(1)
                ctr += 1

        print("Dequeue done")

    def insert_update_episodes(self, parent_id: int, url: str, json_str: str, raw_content: str):
        try:
            # parse json content
            episode = json.loads(raw_content)
        except json.JSONDecodeError:
            print(f"Failed to load raw content of {url},\n{raw_content}")
            return -1
        sel_ep = episode.get("selectedEpisode")

        episode_stream_ids = []

        if sel_ep is not None:
            media = sel_ep.get("media")
            if media is not None:
                presentations = media.get("presentations")
                if presentations is not None:
                    for i in range(len(presentations)):
                        p = presentations[i]
                        width = p.get("width")
                        if width is None:
                            print(f"Failed to retrieve WIDTH {width}")
                            continue
                        height = p.get("height")
                        if height is None:
                            print(f"Failed to retrieve HEIGHT {height}")
                            continue

                        resolution_string = f"{width} x {height}"
                        url = p.get("url")
                        if p.get("url") is None:
                            print(f"Failed to retrieve URL {p}")
                            continue
                        episode_stream_ids.append(self.insert_update_streams(url=url, resolution=resolution_string))

        stream_string = json.dumps(episode_stream_ids)

        # exists:
        self.sq_cur.execute(
            f"SELECT key FROM episodes WHERE "
            f"parent = {parent_id} AND "
            f"URL = '{url}' AND "
            f"json = '{json_str}' AND "
            f"deprecated = 0 AND "
            f"streams = '{stream_string}'")

        # it exists, abort
        if self.sq_cur.fetchone() is not None:
            print("Found active in db")
            self.episode_active_counter += 1
            return

        # exists but is deprecated
        self.sq_cur.execute(
            f"SELECT key FROM episodes WHERE "
            f"parent = {parent_id} AND "
            f"URL = '{url}' AND "
            f"json = '{json_str}' AND "
            f"deprecated = 1 AND "
            f"streams = '{stream_string}'")

        result = self.sq_cur.fetchone()
        if result is not None:
            self.episode_deprecated_counter += 1
            print(
                "Found inactive in db, reacivate and set everything else matching parent, url and series to deprecated")

            # update all entries, to deprecated, unset deprecated where it is here
            self.sq_cur.execute(
                f"UPDATE episodes SET deprecated = 1 WHERE parent = {parent_id} AND URL = '{url}'")
            self.sq_cur.execute(f"UPDATE episodes SET deprecated = 0 WHERE key = {result}")
            return

        # doesn't exist -> insert
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("Inserting")
        self.episode_insert_counter += 1
        self.sq_cur.execute(
            f"INSERT INTO episodes (parent, URL, json, found, streams) VALUES ({parent_id}, '{url}', '{json_str}', '{now}', '{stream_string}')")

    def insert_update_streams(self, url: str, resolution: str):
        # exists:
        self.sq_cur.execute(
            f"SELECT key FROM streams WHERE URL = '{url}' AND resolution = '{resolution}' AND deprecated = 0")

        # it exists, abort
        key = self.sq_cur.fetchone()
        if key is not None:
            self.streams_active_counter += 1
            print("Found active in db")
            return key

        # exists but is deprecated
        self.sq_cur.execute(
             f"SELECT key FROM streams WHERE URL = '{url}' AND resolution = '{resolution}' AND deprecated = 1")

        result = self.sq_cur.fetchone()
        if result is not None:
            self.streams_deprecated_counter += 1
            print(
                "Found inactive in db, reacivate and set everything else matching parent, url and series to deprecated")

            # update all entries, to deprecated, unset deprecated where it is here
            self.sq_cur.execute(f"UPDATE streams SET deprecated = 0 WHERE key = {result}")
            return result

        # doesn't exist -> insert
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("Inserting")
        self.streams_insert_counter += 1
        self.sq_cur.execute(
            f"INSERT INTO streams (URL, resolution, found) VALUES ('{url}', '{resolution}', '{now}')")

        self.sq_cur.execute(
            f"SELECT key FROM streams WHERE URL IS '{url}' AND  resolution IS '{resolution}' AND found IS '{now}'")
        return self.sq_cur.fetchone()

    def deprecate_streams(self):
        self.sq_cur.execute("SELECT COUNT(url) FROM streams WHERE deprecated = 0")
        total = self.sq_cur.fetchone()[0]
        print(total)

        # fetch all is way faster. It might be important in the future that this process is split into multiple
        # subprocesses each with it's one database to search. This is simply the case since the ram required is rather
        # large

        self.sq_cur.execute("SELECT key FROM streams WHERE deprecated = 0")
        rows = self.sq_cur.fetchall()
        count = 0
        dep_count = 0

        for row in rows:
            key = row[0]
            count += 1

            self.sq_cur.execute(f"SELECT key FROM episodes WHERE streams LIKE '%{key}%'")

            if self.sq_cur.fetchone() is None:
                print(f"Deprecating entry: {key}")
                self.sq_cur.execute(f"UPDATE streams SET deprecated = 1 WHERE key = {key}")
                dep_count += 1

            if count % 1000:
                print(f"Done with {(count * 100.0 / total):.2f}%")

        print(f"Deprecated {dep_count} entries")
        print("Done deprecating")

    def reset_counters(self):
        self.episode_deprecated_counter = 0
        self.episode_insert_counter = 0
        self.episode_active_counter = 0

        self.streams_deprecated_counter = 0
        self.streams_insert_counter = 0
        self.streams_active_counter = 0
