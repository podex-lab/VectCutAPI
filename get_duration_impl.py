import subprocess
import json
import re
import struct
import time
from pathlib import Path


def _mp4_mvhd_duration(path_str: str) -> float:
    p = Path(path_str)
    if not p.is_file():
        return 0.0
    data = p.read_bytes()

    def boxes(start, end):
        pos = start
        while pos + 8 <= end:
            size, kind = struct.unpack_from(">I4s", data, pos)
            header = 8
            if size == 1:
                size = struct.unpack_from(">Q", data, pos + 8)[0]
                header = 16
            if size == 0:
                size = end - pos
            if size < header or pos + size > end:
                break
            yield kind, pos + header, pos + size
            pos += size

    for kind, begin, end in boxes(0, len(data)):
        if kind == b"moov":
            for sub, off, stop in boxes(begin, end):
                if sub == b"mvhd":
                    if data[off] == 1:
                        scale = struct.unpack_from(">I", data, off + 20)[0]
                        length = struct.unpack_from(">Q", data, off + 24)[0]
                    else:
                        scale, length = struct.unpack_from(">II", data, off + 12)
                    return float(length) / float(scale) if scale else 0.0
    return 0.0


def probe_media_info(media_url: str) -> dict:
    """
    Probe duration, width, and height using ffprobe or imageio_ffmpeg fallback.
    Returns {'success': bool, 'duration': float, 'width': int, 'height': int, 'has_video': bool, 'error': str|None}
    """
    info = {"success": False, "duration": 0.0, "width": 0, "height": 0, "has_video": False, "error": None}
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        proc = subprocess.run(
            [ffmpeg_exe, "-hide_banner", "-i", str(media_url)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        stderr = proc.stderr or ""
        dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
        if dur_match:
            h, m, s = int(dur_match.group(1)), int(dur_match.group(2)), float(dur_match.group(3))
            info["duration"] = h * 3600 + m * 60 + s
            info["success"] = True

        for line in stderr.splitlines():
            if "Video:" in line:
                info["has_video"] = True
                dim_match = re.search(r"\b(\d{2,5})x(\d{2,5})\b", line)
                if dim_match:
                    info["width"] = int(dim_match.group(1))
                    info["height"] = int(dim_match.group(2))
                break
        if info["success"]:
            return info
    except Exception as e:
        info["error"] = str(e)

    mvhd_dur = _mp4_mvhd_duration(str(media_url))
    if mvhd_dur > 0:
        info["duration"] = mvhd_dur
        info["success"] = True
    return info


def get_video_duration(video_url):
    """
    Get video/audio duration with ffprobe, imageio_ffmpeg, and MP4 mvhd fallback.
    :param video_url: Video or audio file path / URL
    :return: {'success': bool, 'output': float, 'error': str|None}
    """
    result = {"success": False, "output": 0, "error": None}

    # First try imageio_ffmpeg / MP4 header fallback directly (fast & reliable on Windows without global ffprobe)
    probed = probe_media_info(video_url)
    if probed["success"] and probed["duration"] > 0:
        result["success"] = True
        result["output"] = probed["duration"]
        return result

    # Fallback to system ffprobe if available
    try:
        command = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "stream=duration",
            "-show_entries", "format=duration",
            "-print_format", "json",
            str(video_url),
        ]
        process = subprocess.run(command, capture_output=True, text=True, timeout=10, check=True)
        info = json.loads(process.stdout)
        media_streams = [s for s in info.get("streams", []) if "duration" in s]
        if media_streams:
            result["output"] = float(media_streams[0]["duration"])
            result["success"] = True
        elif "format" in info and "duration" in info["format"]:
            result["output"] = float(info["format"]["duration"])
            result["success"] = True
        else:
            result["error"] = "Audio/video duration information not found."
    except Exception as e:
        result["error"] = probed.get("error") or str(e)

    return result
