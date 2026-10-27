import os
import re
import subprocess
import glob  # 新增导入
import hashlib
import time
import requests
from urllib.parse import parse_qs, urlencode, urlparse


# Bilibili uses this permutation to derive the WBI signing key.  Keeping the
# fallback on the signed playback API avoids the public webpage endpoint, which
# is frequently rejected with HTTP 412 on automated/network-proxied requests.
_WBI_MIXIN_KEY_TABLE = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]


def _get_wbi_mixin_key(wbi_img):
    """Build the temporary WBI key returned by Bilibili's navigation API."""
    img_key = os.path.splitext(os.path.basename(urlparse(wbi_img["img_url"]).path))[0]
    sub_key = os.path.splitext(os.path.basename(urlparse(wbi_img["sub_url"]).path))[0]
    source_key = img_key + sub_key
    return "".join(source_key[index] for index in _WBI_MIXIN_KEY_TABLE)[:32]


def _sign_wbi_params(params, mixin_key):
    """Return URL-encoded, signed query parameters for a WBI endpoint."""
    signed_params = dict(params)
    signed_params["wts"] = int(time.time())
    signed_params = {
        key: re.sub(r"[!\\'()*]", "", str(value))
        for key, value in sorted(signed_params.items())
    }
    query = urlencode(signed_params)
    return f"{query}&w_rid={hashlib.md5((query + mixin_key).encode()).hexdigest()}"


def _get_with_retries(session, url, *, attempts=3, **kwargs):
    """Retry transient proxy/CDN failures without hiding the final error."""
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            response = session.get(url, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            last_error = error
            if attempt < attempts:
                print(f"连接失败，正在重试（{attempt}/{attempts - 1}）...")
                time.sleep(attempt)
    raise last_error


def _download_media_from_urls(session, media_urls, headers, temporary_path, expected_size):
    """Try the playback CDNs, resuming a partial response on the next CDN."""
    downloaded_size = 0
    last_error = None
    for index, media_url in enumerate(media_urls, start=1):
        request_headers = dict(headers)
        if downloaded_size:
            request_headers["Range"] = f"bytes={downloaded_size}-"
        print(f"连接视频线路 {index}/{len(media_urls)}，已下载 {downloaded_size / 1048576:.1f} MB...")
        try:
            response = _get_with_retries(
                session,
                media_url,
                attempts=1,
                headers=request_headers,
                stream=True,
                timeout=(15, 20),
            )
            with response:
                if downloaded_size:
                    content_range = response.headers.get("Content-Range", "")
                    if response.status_code == 200:
                        # This CDN ignored Range and sent the whole file.
                        print("该线路不支持断点续传，从头下载...")
                        downloaded_size = 0
                    elif response.status_code != 206 or not content_range.startswith(
                        f"bytes {downloaded_size}-"
                    ):
                        raise RuntimeError(f"备用线路返回了无效的续传范围: {content_range}")
                mode = "ab" if downloaded_size else "wb"
                last_report_size = downloaded_size
                last_report_time = time.monotonic()
                with open(temporary_path, mode) as media_file:
                    for chunk in response.iter_content(chunk_size=1024 * 256):
                        if not chunk:
                            continue
                        media_file.write(chunk)
                        downloaded_size += len(chunk)
                        now = time.monotonic()
                        if (downloaded_size - last_report_size >= 5 * 1048576
                                or now - last_report_time >= 15):
                            progress = (
                                f"{downloaded_size / 1048576:.1f}/{expected_size / 1048576:.1f} MB"
                                if expected_size else f"{downloaded_size / 1048576:.1f} MB"
                            )
                            print(f"视频下载进度: {progress}")
                            last_report_size = downloaded_size
                            last_report_time = now
            if expected_size and downloaded_size != expected_size:
                raise RuntimeError(
                    f"视频未完整下载（{downloaded_size}/{expected_size} 字节）"
                )
            return
        except (requests.RequestException, OSError, RuntimeError) as error:
            last_error = error
            if expected_size and downloaded_size == expected_size:
                # Some servers close the connection abruptly after sending
                # the final byte; the size check still confirms completion.
                return
            if index < len(media_urls):
                print(f"视频线路 {index} 中断（已下载 {downloaded_size / 1048576:.1f} MB），切换备用线路...")
    raise RuntimeError(f"所有B站视频线路均下载失败: {last_error}")


def _download_bilibili_via_wbi(file_id, output_dir, *, direct=True):
    """Download the first Bilibili page through the signed playback endpoint.

    yt-dlp remains the preferred path.  This fallback is deliberately limited
    to a single video page because the rest of the application expects one
    media file for a submitted link.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    session = requests.Session()
    # This host's configured proxy returns 412 for Bilibili and can interrupt
    # CDN transfers.  requests otherwise picks that proxy up automatically.
    session.trust_env = not direct
    print("WBI接口使用直连网络..." if direct else "WBI接口尝试系统代理...")

    print("正在获取B站视频分P信息...")
    page_response = _get_with_retries(
        session,
        "https://api.bilibili.com/x/player/pagelist",
        params={"bvid": file_id},
        headers=headers,
        timeout=15,
    )
    page_response.raise_for_status()
    page_data = page_response.json()
    pages = page_data.get("data") or []
    if page_data.get("code") != 0 or not pages:
        raise RuntimeError(f"获取视频分P信息失败: {page_data.get('message', '无可下载分P')}")

    print("正在获取B站播放接口签名...")
    nav_response = _get_with_retries(
        session,
        "https://api.bilibili.com/x/web-interface/nav",
        headers=headers,
        timeout=15,
    )
    nav_response.raise_for_status()
    wbi_img = (nav_response.json().get("data") or {}).get("wbi_img")
    if not wbi_img:
        raise RuntimeError("无法获取B站播放接口签名信息")

    mixin_key = _get_wbi_mixin_key(wbi_img)
    print("正在获取视频播放地址...")
    query = _sign_wbi_params(
        {
            "bvid": file_id,
            "cid": pages[0]["cid"],
            "qn": 64,  # 720P; broadly available without requiring an account
            "fnval": 0,  # request one directly playable MP4 instead of DASH tracks
            "fourk": 0,
        },
        mixin_key,
    )
    play_response = _get_with_retries(
        session,
        f"https://api.bilibili.com/x/player/wbi/playurl?{query}",
        headers=headers,
        timeout=15,
    )
    play_response.raise_for_status()
    play_data = play_response.json()
    durls = (play_data.get("data") or {}).get("durl") or []
    if play_data.get("code") != 0 or not durls:
        raise RuntimeError(f"获取视频播放地址失败: {play_data.get('message', '未返回MP4地址')}")
    if len(durls) != 1:
        raise RuntimeError("该视频返回多个媒体分段，暂不支持兜底直连下载")

    title = pages[0].get("part") or file_id
    safe_title = re.sub(r'[\\\\/:*?"<>|]+', "_", title).strip() or file_id
    output_path = os.path.join(output_dir, f"{safe_title}.mp4")
    temporary_path = f"{output_path}.part"
    expected_size = durls[0].get("size")
    media_urls = [durls[0]["url"], *durls[0].get("backup_url", [])]
    if expected_size:
        print(f"视频大小约 {expected_size / 1048576:.1f} MB，开始下载...")
    _download_media_from_urls(session, media_urls, headers, temporary_path, expected_size)
    os.replace(temporary_path, output_path)

    print(f"WBI直链下载成功: {output_path}")
    return file_id

def ensure_folders_exist(output_dir):
    if not os.path.exists("bilibili_video"):
        os.makedirs("bilibili_video")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    if not os.path.exists("outputs"):
        os.makedirs("outputs")


def _has_complete_video(output_dir):
    """Reuse an existing video only after FFmpeg decodes it without errors."""
    for extension in ("mp4", "mkv", "flv", "webm"):
        for path in sorted(glob.glob(os.path.join(output_dir, f"*.{extension}"))):
            print(f"检查已有视频是否完整: {path}")
            try:
                result = subprocess.run(
                    ["ffmpeg", "-v", "error", "-i", path, "-f", "null", "-"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
            except FileNotFoundError:
                print("未找到FFmpeg，无法校验已有视频，将重新下载。")
                return False
            if result.returncode == 0 and not result.stderr.strip():
                print(f"复用已下载的视频: {path}")
                return True
            print(f"已有视频不完整，将重新下载: {path}")
    return False

def _detect_source(link_or_bv: str):
    """简单判断来源，返回(source, identifier, url)。"""
    if link_or_bv.startswith("http"):
        if "bilibili.com" in link_or_bv:
            matches = re.findall(r'BV[A-Za-z0-9]+', link_or_bv)
            if matches:
                return "bilibili", matches[0], f"https://www.bilibili.com/video/{matches[0]}"
        if "youtube.com" in link_or_bv or "youtu.be" in link_or_bv:
            # 尝试提取 YouTube 视频 ID
            parsed = urlparse(link_or_bv)
            video_id = None
            if "youtu.be" in parsed.netloc:
                video_id = parsed.path.strip("/")
            else:
                qs = parse_qs(parsed.query)
                video_id = (qs.get("v") or [None])[0]
            if video_id:
                return "youtube", f"yt_{video_id}", link_or_bv
            # 没拿到 ID 也允许下载，使用完整链接
            return "youtube", "yt_video", link_or_bv
        # 其他站点仍用 yt-dlp 下载
        return "generic", "video", link_or_bv
    # 非链接，尝试按 BV 处理
    if not link_or_bv.startswith("BV"):
        link_or_bv = "BV" + link_or_bv
    return "bilibili", link_or_bv, f"https://www.bilibili.com/video/{link_or_bv}"


def download_video(link_or_bv):
    """
    下载视频（B站/YouTube/其他支持的站点）。
    参数:
        link_or_bv: 视频链接或BV号
    返回:
        成功时返回文件标识符（用于后续音频处理），失败时返回None
    """
    source, file_id, video_url = _detect_source(str(link_or_bv))
    output_dir = f"bilibili_video/{file_id}"  # 统一放在 bilibili_video 下，便于后续处理
    ensure_folders_exist(output_dir)
    if source == "bilibili" and _has_complete_video(output_dir):
        return file_id
    print(f"使用yt-dlp下载视频: {video_url}")
    try:
        # yt-dlp命令：-o指定输出路径和文件名，--no-playlist只下载单个视频
        # 使用%(title)s.%(ext)s作为文件名模板，但会被output_dir覆盖路径部分
        output_template = os.path.join(output_dir, "%(title)s.%(ext)s")
        extra_headers = []
        extractor_args = []
        
        if source == "bilibili":
            extra_headers = [
                "--proxy", "",  # direct connection; avoids proxy-side 412/SSL errors
                "--socket-timeout", "20",
                "--referer", "https://www.bilibili.com",
                "--add-header", "User-Agent: Mozilla/5.0",
            ]
        elif source == "youtube":
            # 添加 YouTube headers 以避免 403 错误
            extra_headers = [
                "--add-header", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "--add-header", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "--add-header", "Accept-Language: en-US,en;q=0.5",
                "--referer", "https://www.youtube.com/"
            ]
            # 使用 android 客户端避免 SABR 流问题和 403 错误
            # android 客户端通常更稳定，不会触发 YouTube 的 SABR 流限制
            extractor_args = ["--extractor-args", "youtube:player_client=android"]

        format_args = []
        if source == "youtube":
            # 使用更灵活的格式选择，避免触发 SABR 流的格式
            # 优先选择 android 客户端支持的格式，避免 web 客户端的 SABR 流问题
            format_args = ["-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"]

        # 实时流式输出下载进度，避免界面长时间没有日志刷新、看起来像卡住
        # --newline 让进度条按行输出，--progress-delta 1 控制每秒最多刷新一次，避免刷屏
        process = subprocess.Popen(
            [
                "yt-dlp",
                "-o", output_template,
                "--no-playlist",
                "--newline",
                "--progress-delta", "1",
                *extractor_args,
                *format_args,
                *extra_headers,
                video_url,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        for line in iter(process.stdout.readline, ""):
            line = line.rstrip("\n")
            if line:
                print(line)
        process.stdout.close()
        returncode = process.wait()

        if returncode == 0:
            # 检查是否真的下载了视频文件
            video_files = glob.glob(os.path.join(output_dir, "*.mp4"))
            if not video_files:
                # 也检查其他视频格式
                video_files = glob.glob(os.path.join(output_dir, "*.flv"))
                if not video_files:
                    video_files = glob.glob(os.path.join(output_dir, "*.mkv"))
                if not video_files:
                    video_files = glob.glob(os.path.join(output_dir, "*.webm"))
            
            if video_files:
                print(f"视频已成功下载到目录: {output_dir}")
                # 删除xml文件和其他不需要的文件
                xml_files = glob.glob(os.path.join(output_dir, "*.xml"))
                for xml_file in xml_files:
                    try:
                        os.remove(xml_file)
                    except:
                        pass
                return file_id
            else:
                print(f"下载完成但未找到视频文件: {output_dir}")
        else:
            print(f"yt-dlp下载失败，返回码: {returncode}")
    except FileNotFoundError:
        print("错误: 未找到yt-dlp命令。请先安装yt-dlp: pip install yt-dlp")
    except Exception as e:
        print("使用yt-dlp下载发生错误:", str(e))
        import traceback
        print(traceback.format_exc())

    if source != "bilibili":
        return None  # 非B站到这里直接失败

    # 网页解析被 412 拦截时，改用带签名的官方播放接口。
    print("yt-dlp未能下载，切换到WBI播放接口直链下载...")
    for direct in (True, False):
        try:
            return _download_bilibili_via_wbi(file_id, output_dir, direct=direct)
        except Exception as e:
            print("WBI直链下载失败:", str(e))
    return None
