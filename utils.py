import os
import re
import subprocess
import glob  # 新增导入
import requests
from urllib.parse import urlparse
from urllib.parse import parse_qs

def ensure_folders_exist(output_dir):
    if not os.path.exists("bilibili_video"):
        os.makedirs("bilibili_video")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    if not os.path.exists("outputs"):
        os.makedirs("outputs")

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
    print(f"使用yt-dlp下载视频: {video_url}")
    try:
        # yt-dlp命令：-o指定输出路径和文件名，--no-playlist只下载单个视频
        # 使用%(title)s.%(ext)s作为文件名模板，但会被output_dir覆盖路径部分
        output_template = os.path.join(output_dir, "%(title)s.%(ext)s")
        extra_headers = []
        if source == "bilibili":
            extra_headers = ["--referer", "https://www.bilibili.com", "--add-header", "User-Agent: Mozilla/5.0"]

        format_args = []
        if source == "youtube":
            # 优先下载 mp4 + m4a，避免 webm/opus 解析问题
            format_args = ["-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best"]

        result = subprocess.run(
            [
                "yt-dlp",
                "-o", output_template,
                "--no-playlist",
                *format_args,
                *extra_headers,
                video_url,
            ],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            # 打印下载信息
            if result.stdout:
                print(result.stdout)
            
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
            print("yt-dlp下载失败:", result.stderr or result.stdout)
    except FileNotFoundError:
        print("错误: 未找到yt-dlp命令。请先安装yt-dlp: pip install yt-dlp")
    except Exception as e:
        print("使用yt-dlp下载发生错误:", str(e))
        import traceback
        print(traceback.format_exc())

    if source != "bilibili":
        return None  # 非B站到这里直接失败

    # 如果yt-dlp失败，尝试使用官方接口直链下载，规避412校验
    print("切换到API直链下载...")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.bilibili.com",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        session = requests.Session()
        # 先访问首页拿基础cookie，避免接口返回412
        session.get("https://www.bilibili.com", headers=headers, timeout=10)

        # 获取cid等信息
        view_resp = session.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": file_id},
            headers=headers,
            timeout=10,
        ).json()
        if view_resp.get("code") != 0:
            print(f"获取视频信息失败: {view_resp.get('message')}")
            return None
        cid = view_resp["data"]["cid"]
        title = view_resp["data"]["title"]

        play_resp = session.get(
            "https://api.bilibili.com/x/player/playurl",
            params={
                "bvid": file_id,
                "cid": cid,
                "qn": 80,  # 720P，兼顾下载速度
                "fnval": 0,
                "platform": "html5",
                "high_quality": 1,
            },
            headers=headers,
            timeout=10,
        ).json()
        durls = play_resp.get("data", {}).get("durl") or []
        if not durls:
            print(f"直链获取失败: {play_resp.get('message')}")
            return None

        video_url = durls[0]["url"]
        parsed_path = urlparse(video_url).path
        ext = os.path.splitext(parsed_path)[1] or ".mp4"
        safe_title = re.sub(r'[\\\\/:*?"<>|]+', "_", title).strip() or file_id
        output_path = os.path.join(output_dir, f"{safe_title}{ext}")

        with session.get(video_url, headers=headers, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            with open(output_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
        print(f"直链下载成功: {output_path}")
        return file_id
    except Exception as e:
        print("直链下载失败:", str(e))
        import traceback
        print(traceback.format_exc())
        return None
