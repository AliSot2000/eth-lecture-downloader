import datetime
import requests as rq
from dataclasses import dataclass
import random


@dataclass
class Proxy:
    ip: str
    port: str


class RandomProxy:
    def __init__(self):
        self.proxy_list = []
        self.response_json_dict = {}
        self.last_update = datetime.datetime.now()
        self.update_proxies()

    def get_proxy(self):
        self.__update_one_time()
        return random.choice(self.proxy_list)

    def update_proxies(self):
        res = rq.get("https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc", headers={"user-agent": "Proxy-list-getter"})

        if res.ok:
            self.response_json_dict = res.json()
            self.__parse_proxies()

    def __parse_proxies(self):
        proxy_objs = self.response_json_dict["data"]
        self.proxy_list = []

        for o in proxy_objs:
            if o["anonymityLevel"] == "elite":
                self.proxy_list.append(Proxy(ip=o["ip"], port=o["port"]))

        self.last_update = datetime.datetime.now()

    def __update_one_time(self):
        if (datetime.datetime.now() - self.last_update).total_seconds() > 600:
            self.update_proxies()


if __name__ == "__main__":

    rdp = RandomProxy()
