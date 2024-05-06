from common import compress_cpu, compress_gpu, CompressionArgument
import datetime


def get_cmd_list():
    """
    Builds teh default command list for handbrake.
    """
    return ['HandBrakeCLI', '-v', '5', '-Z', 'Very Fast 1080p30', '-f', 'av_mp4', '-q', '29', '-w', '1920',
                '-l', '1080', '--keep-display-aspect']


if __name__ == "__main__":
    raw_list = get_cmd_list()
    sp = "/home/alisot2000/Desktop/IML_24/2024-02-20T14_13.mp4"
    hp = "/home/alisot2000/Desktop/IML_24/.2024-02-20T14_13.mp4"
    dp = "/home/alisot2000/Desktop/IML_24_comp/compression-benchmark/2024-02-20T14_13_gpu_cli_3.mp4"
    file_list = ["-i", sp,
                 "-o", dp,
                 "-e", "nvenc_h264"]
    args = CompressionArgument(
        command_list=raw_list + file_list,
        source_path=sp,
        destination_path=dp,
        keep_original=True,
        hidden_path=hp
    )
    start = datetime.datetime.now()
    compress_cpu(args, 1)
    end = datetime.datetime.now()
    print(f"Time taken: {(end - start).total_seconds()}")