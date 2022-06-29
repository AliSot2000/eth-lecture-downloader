import datetime
# from eth_loader.stream_loader import ConcurrentETHIndexer
from eth_loader.indexer import ConcurrentETHIndexer
from eth_loader.metadata_loader import EpisodeLoader
from eth_loader.stream_loader import BetterStreamLoader, SpecLogin

# HandBrakeCLI

if __name__ == "__main__":
    start = datetime.datetime.now()
    print("Started")
    eid = ConcurrentETHIndexer("seq_sites.db")
    eid.index_video_eth()
    eid.gen_parent()
    del eid
    el = EpisodeLoader("seq_sites.db")
    el.download()
    del el
    bsl = BetterStreamLoader("seq_sites.db", user_name="asotoudeh", password="3Xtv56HwjnpC5$Yx44PH!Tjt", spec_login=[SpecLogin(password="fG9LdsA", username="gro-21w", url="https://www.video.ethz.ch/lectures/d-infk/2021/autumn/252-0027-00L")])
    bsl.initiator()
    # bsl.deprecate_streams()

    end = datetime.datetime.now()
    print(f"required {(end - start).total_seconds()}s")
