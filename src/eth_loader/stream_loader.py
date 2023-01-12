import os
import traceback

import requests as rq
import multiprocessing as mp
import queue
import time
import pickle
from threading import Thread
import json
from dataclasses import dataclass
from typing import List
from sqlite3 import *
import datetime


# gro-21w
# fG9LdsA


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
        # TODO: logging and debug shit
        print(f"{identifier} error {result.status_code}")

    return {"url": url, "status": result.status_code, "content": content, "parent_id": parent_id}


def handler(worker_nr: int, command_queue: mp.Queue, result_queue: mp.Queue):
    """
    Function executed in a worker thread. The function tries to download the given url in the queue. If the queue is
    empty for 20s, it will kill itself.

    :param worker_nr: Itendifier for debugging
    :param command_queue: Queue containing dictionaries containing all relevant information for downloading
    :param result_queue: Queue to put the results in. Handled in main thread.
    :return:
    """
    # TODO: logging and debug shit
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
    # TODO: logging and debug shit
    print(f"{worker_nr} Terminated")


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
    """
    Class loads all stream file urls for the given database.
    """

    def __init__(self, db: str, user_name: str = None, password: str = None,
                 spec_login: List[SpecLogin] = None):

        """
        Perform initialisation and acquire the login cookie for the indexing.

        :param db: path to the database to use.
        :param user_name: ETHZ-LDAP username
        :param password: LDAP password
        :param spec_login: list of SpecLogin Dataclass objects. Containing an url for which the login is intended,
            the username and the password
        """

        self.db_path = os.path.abspath(db)
        self.download_list = []

        self.sq_con = Connection(self.db_path)
        self.sq_cur = self.sq_con.cursor()

        self.get_episode_urls()
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

        # TODO: logger and debug shit
        print(f"TODO: {self.nod}")
        time.sleep(10)

        self.general_cookie = None
        self.login(user_name, password)

    def get_episode_urls(self):
        """
        Retrieves the urls for all episodes from the metadata (series-metadata.json of first episode) table.
        Puts them into the download_list.

        :return:
        """
        # verify existence of source table
        self.verify_args_table()

        # select first entry
        self.sq_cur.execute("SELECT key, json, URL FROM metadata WHERE deprecated = 0")
        row = self.sq_cur.fetchone()

        while row is not None:
            parent_id = row[0]
            content = row[1]
            parent_url = row[2]

            # parent url without file extension
            strip_url = parent_url.replace(".html", "").replace(".series-metadata.json", "")

            # why was this again important?
            content_default = content.replace("''", "'")

            # cannot process a html site. We skip this entry.
            if "<!DOCTYPE html>" in content_default:
                # TODO: logging and debug shit
                print(f"Found an html site: {parent_url}")

                row = self.sq_cur.fetchone()
                continue

            # try to retrieve the json information. from the content.
            try:
                result = json.loads(content_default)
            except json.JSONDecodeError:
                # TODO: logging and debug shit
                print(traceback.format_exc())
                print(content_default)
                print(parent_url)

                row = self.sq_cur.fetchone()
                continue

            # continue with the dict
            result: dict

            # verify existence of episodes key
            if result.get("episodes") is not None:
                episodes = result.get("episodes")

                # iterate over episodes.
                for ep in episodes:
                    ep_id = ep.get("id")

                    # verify existence of episode id.
                    if ep_id is None:
                        # TODO: logging and debug shit
                        print(f"Failed to generate id with Content:\n{content_default}")
                        continue

                    # episode url with file extension
                    ep_url = f"{strip_url}/{ep_id}.series-metadata.json"

                    self.download_list.append(EpisodeEntry(parent_id=parent_id, series_url=parent_url,
                                                           episode_url=ep_url))

            else:
                # TODO: logging and debug shit
                print(f"No episodes found {parent_url}")

            row = self.sq_cur.fetchone()

    def verify_args_table(self):
        """
        Verifies a Table exists inside the given sqlite database.
        :return:
        """

        # TODO: Verify columns and type match

        self.sq_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='metadata'")

        if self.sq_cur.fetchone() is None:
            raise ValueError("didn't find the 'sites' table inside the given database.")

    def check_results_table(self):
        """
        Checks if the tables for the results exist already in the database and otherwise creates the tables.
        :return:
        """
        # check if the episodes table exists already.
        self.sq_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='episodes'")

        # if it doesn't exist, create a results table.
        if self.sq_cur.fetchone() is None:
            self.sq_cur.execute("CREATE TABLE episodes "
                                "(key INTEGER PRIMARY KEY AUTOINCREMENT, "
                                "parent INTEGER, "
                                "URL TEXT , "
                                "json TEXT,"
                                "deprecated INTEGER DEFAULT 0 CHECK (episodes.deprecated >= 0 AND episodes.deprecated <= 1),"
                                "found TEXT,"
                                "last_seen TEXT, "
                                "streams TEXT)")

        # check that the streams table exists
        self.sq_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='streams'")

        # create the table if it doesn't exist.
        if self.sq_cur.fetchone() is None:
            self.sq_cur.execute("CREATE TABLE streams "
                                "(key INTEGER PRIMARY KEY AUTOINCREMENT, "
                                "URL TEXT , "
                                "resolution TEXT,"
                                "deprecated INTEGER DEFAULT 0 CHECK (deprecated >= 0 AND deprecated <= 1),"
                                "found TEXT, "
                                "last_seen TEXT)")

            self.sq_cur.execute(
                "INSERT INTO streams (key, URL, resolution, found) VALUES (-1, 'dummy', 'dummy', 'dummy')")

    def spawn(self, threads: int = 100):
        """
        Spawns worker threads.

        :param threads: number of threads to spawn 1-10000
        :return:
        """
        if not 1 < threads < 10000:
            raise ValueError("Thread number outside supported range [1:10'000]")

        self.workers = []
        for i in range(threads):
            t = Thread(target=handler, args=(i, self.command_queue, self.result_queue))
            t.start()
            self.workers.append(t)

        print("Workers Spawned")

    def initiator(self, workers: int = 100):
        """
        Runs the entire job basically. Starts all threads, retrieves all values, stores the database and does the
        clenaup.

        :param workers: number of workers in parallel.
        :return:
        """
        self.spawn(workers)
        self.enqueue_job()
        self.dequeue_job()

        while self.workers_alive():
            time.sleep(30)
            print("Initiator Thread Sleeping Workers")

        self.cleanup()
        self.sq_con.commit()
        self.deprecate_streams()
        self.sq_con.commit()
        print("DONE")

    def cleanup(self):
        """
        Waits for all worker processes to terminate and then joins them.
        :return:
        """
        for worker in self.workers:
            worker: Thread
            worker.join(10)

    def workers_alive(self):
        """
        Function to verify that at least one of the workers hasn't exited.
        :return:
        """
        for worker in self.workers:
            worker: Thread
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
            # TODO: logging and debug shit
            print("No Credentials")
            return

        login = rq.post(url="https://video.ethz.ch/j_security_check",
                        headers={"user-agent": "lol herre"}, data={"_charset_": "utf-8", "j_username": usr,
                                                                   "j_password": pw,
                                                                   "j_validate": True})

        if login.ok:
            self.general_cookie = login.cookies

        elif login.status_code == 403:
            # TODO: logging and debug shit
            print("Wrong Credentials")

        else:
            # TODO: logging and debug shit
            print(login.status_code)
            print(vars(login))

    def spec_login(self, strip_url: str, usr: str, pw: str, other_cookies=None):
        """
        Provide the url as the series-metadata or html for the course site

        :param other_cookies: other cookies to be joined with the selected cookie (so both login information is sent)
        :param pw: password for the specific login
        :param usr: username for the specific login
        :param strip_url: url where to perform the specific login
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
            # TODO: logging and debug shit
            print(login.status_code)
            print(vars(login))
            return self.general_cookie

    def enqueue_job(self):
        """
        Enqueues all episodes in the download_list.

        It verifies that url of the series or the episode itself is not in
        the spec_login list.

        If it is, it performs the login for the specific episode or series and adds the cookie
        authentication to the command for the downloaders.
        :return:
        """
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
        """
        Dequeues the results from the results queue. It then stores the results in the results table.
        :return:
        """
        # counter to prevent infinite loop
        ctr = 0
        while ctr < 20:
            # dequeue
            if not self.result_queue.empty():
                try:
                    res = self.result_queue.get()

                    # verify the correct download of the episode metadata
                    if res["status"] == 200:

                        # TODO NEEDS TO BE STORED IN b64
                        content = res["content"].replace("'", "''")

                        # why is res['content'] read twice?
                        self.insert_update_episodes(parent_id=res["parent_id"], url=res["url"],
                                                    json_str=content, raw_content=res["content"])
                    else:
                        # TODO: logging and debug shit
                        print(f"url {res['url']} with status code {res['status']}")
                    ctr = 0
                except Exception as e:
                    # TODO: logging and debug shit
                    print("\n\n\n FUCKING EXCEPTION \n\n\n")
                    print(traceback.format_exc())
            else:
                time.sleep(1)
                ctr += 1

    def insert_update_episodes(self, parent_id: int, url: str, json_str: str, raw_content: str):
        """
        Given the parent_id (key), the url of the episode, the json_string associated with the episode and the content
        of the episode site, it updates the stream and episodes table. Updating or inserting depending on presence and
        deprecated state.

        :param parent_id: key of the parent entry. (Series in XXX table) # TODO look up table
        :param url: url of the episode that was downloaded
        :param json_str: json string of the series site???
        :param raw_content: json content that was the response for the series.
        :return:
        """
        try:
            # parse json content
            episode = json.loads(raw_content)
        except json.JSONDecodeError:
            # TODO: logging and debug shit
            print(f"Failed to load raw content of {url},\n{raw_content}")
            return -1

        # list of ids in streams table associated with current episode.
        stream_string = json.dumps(self.retrieve_streams(json_obj=episode, parent_id=parent_id))
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # exists:
        self.sq_cur.execute(
            f"SELECT key FROM episodes WHERE "
            f"parent = {parent_id} AND "
            f"URL = '{url}' AND "
            f"json = '{json_str}' AND "
            f"deprecated = 0 AND "
            f"streams = '{stream_string}'")

        # it exists, abort
        result = self.sq_cur.fetchone()
        if result is not None:
            # TODO: logging and debug shit
            self.sq_cur.execute(f"UPDATE episodes SET last_seen = '{now}' WHERE key = {result[0]}")
            print("Found active in db")
            return result[0]

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
            # TODO: logging and debug shit
            print(
                "Found inactive in db, reactivate and set everything else matching parent, url and series to deprecated")

            # deprecate any entry matching only parent and url (i.e. not matching json)
            # then update the one with the matching json
            self.sq_cur.execute(
                f"UPDATE episodes SET deprecated = 1 WHERE parent = {parent_id} AND URL = '{url}'")
            self.sq_cur.execute(f"UPDATE episodes SET deprecated = 0, last_seen = '{now}' WHERE key = {result[0]}")
            return result[0]

        # doesn't exist -> insert
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # TODO: logging and debug shit
        print("Inserting")
        self.sq_cur.execute(
            f"INSERT INTO episodes (parent, URL, json, found, streams, last_seen) "
            f"VALUES ({parent_id}, '{url}', '{json_str}', '{now}', '{stream_string}', '{now}')")

    def retrieve_streams(self, json_obj: dict, parent_id: int):
        """
        Given the .series_metadata.json of a given episode, retrieve the streams and store them in the db.

        :param json_obj: content of the series_metadata.json
        :param parent_id: key of parent in db for identification if error occures
        :return:
        """
        episode_stream_ids = []

        # verify selectedEpisode key exists
        sel_ep = json_obj.get("selectedEpisode")
        if sel_ep is None:
            return []

        # verify media key exists
        media = sel_ep.get("media")
        if media is None:
            return []

        # verify presentations key exists
        presentations = media.get("presentations")
        if presentations is None:
            return []

        # go through and get the urls of the presentations
        for i in range(len(presentations)):
            p = presentations[i]
            width = p.get("width")

            # try to retrieve width, ignore if it doesn't exist
            # TODO: proceed but put warning
            if width is None:
                # TODO: logging and debug shit
                print(f"Failed to retrieve WIDTH {parent_id}")
                continue

            height = p.get("height")

            # try to retrieve height, ignore if it doesn't exist
            # TODO: proceed but put warning
            if height is None:
                # TODO: logging and debug shit
                print(f"Failed to retrieve HEIGHT {parent_id}")
                continue

            resolution_string = f"{width} x {height}"
            url = p.get("url")

            # verify url key exists
            if p.get("url") is None:
                # TODO: logging and debug shit
                print(f"Failed to retrieve URL {p}")
                continue

            episode_stream_ids.append(self.insert_update_streams(url=url, resolution=resolution_string))

        return episode_stream_ids

    def insert_update_streams(self, url: str, resolution: str):
        """
        Insert the stream into the database. If it exists update the database accordingly.

        :param url: url of the stream
        :param resolution: resolution of the stream
        :return:
        """
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # exists:
        self.sq_cur.execute(
            f"SELECT key FROM streams WHERE URL = '{url}' AND resolution = '{resolution}' AND deprecated = 0")

        # it exists, abort
        key = self.sq_cur.fetchone()
        if key is not None:
            # TODO: logging and debug shit
            print("Found active in db")
            self.sq_cur.execute(f"UPDATE streams SET last_seen = '{now}' WHERE key = {key[0]}")
            return key[0]

        # exists but is deprecated
        self.sq_cur.execute(
            f"SELECT key FROM streams WHERE URL = '{url}' AND resolution = '{resolution}' AND deprecated = 1")

        result = self.sq_cur.fetchone()
        if result is not None:
            # TODO: logging and debug shit
            print(
                "Found inactive in db, reacivate and set everything else matching parent, url and series to deprecated")

            # update all entries, to deprecated, unset deprecated where it is here (???)
            # update to not deprecated where the key matches.
            self.sq_cur.execute(f"UPDATE streams SET deprecated = 0, last_seen = '{now}' WHERE key = {result[0]}")
            return result[0]

        # doesn't exist -> insert
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # TODO: logging and debug shit
        print("Inserting")
        self.sq_cur.execute(
            f"INSERT INTO streams (URL, resolution, found, last_seen) "
            f"VALUES ('{url}', '{resolution}', '{now}', '{now}')")

        self.sq_cur.execute(
            f"SELECT key FROM streams WHERE URL IS '{url}' AND  resolution IS '{resolution}' AND found IS '{now}'")

        # return the key
        return self.sq_cur.fetchone()[0]

    def deprecate_streams(self):
        """
        Iterate over all episodes that aren't deprecated and make them deprecated if there is no episode entry
        storing them.
        :return:
        """
        self.sq_cur.execute("SELECT key FROM streams WHERE deprecated = 0")

        row = self.sq_cur.fetchone()
        while row is not None:
            key = row[0]

            self.sq_cur.execute(f"SELECT key FROM episodes WHERE streams LIKE '%{key}%'")

            if self.sq_cur.fetchone() is None:
                print(f"Deprecating entry: {key}")
                self.sq_cur.execute(f"UPDATE streams SET deprecated = 1 WHERE key = {key}")

            self.sq_cur.execute("SELECT key FROM streams WHERE deprecated = 0")
            row = self.sq_cur.fetchone()
