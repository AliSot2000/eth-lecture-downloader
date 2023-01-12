import datetime
from eth_loader.site_indexer import ConcurrentETHSiteIndexer
from eth_loader.metadata_loader import EpisodeLoader
from eth_loader.stream_loader import BetterStreamLoader, SpecLogin
from secrets import user_name, password, spec_login

if __name__ == "__main__":
    path = "/home/alisot2000/Documents/01_ReposNCode/ETH-Lecture-Indexer/scripts/seq_sites.db"
    index_start = datetime.datetime.now()
    print("Started")
    eid = ConcurrentETHSiteIndexer(path)
    eid.index_video_eth()
    eid.gen_parent()
    end = datetime.datetime.now()
    print(f"required {(end - index_start).total_seconds()}s")

    start = datetime.datetime.now()
    print("Started")
    eid = EpisodeLoader(path)
    eid.download()
    eid.deprecate(dt=index_start)
    end = datetime.datetime.now()
    print(f"required {(end - start).total_seconds()}s")

    start = datetime.datetime.now()
    print("Started")
    eid = BetterStreamLoader(db=path, user_name=user_name, password=password, spec_login=spec_login)
    eid.initiator()
    end = datetime.datetime.now()
    print(f"required {(end - start).total_seconds()}s")
