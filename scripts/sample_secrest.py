from common import SeriesArgs

user_name = "<your username>"
password = "<your password>"
spec_login = [
    # url="https://www.video.ethz.ch/lectures/d-infk/2021/autumn/252-0027-00L"   # EXAMPLE
    SeriesArgs(password="<lecture password>",
              username="<lecture username>",
               folder="<path to download>",
                compressed_folder="<path to compressed download>",
              url="<url to lecture>")
]