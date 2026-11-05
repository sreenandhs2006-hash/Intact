"""Full decode with PyAV: every packet, every frame, every decoder message.

For each frame we keep its ORIGINAL presentation timestamp (before any 30 FPS
conversion) and a small grayscale thumbnail difference to the previous frame,
used later for content-based duplicate / skip detection.
"""
import av
import av.logging
import cv2
import numpy as np

THUMB = (160, 90)  # small enough to be fast, large enough to see motion
LEVELS = {8: "fatal", 16: "error", 24: "warning"}


def _thumb(frame):
    gray = frame.to_ndarray(format="gray")
    return cv2.resize(gray, THUMB, interpolation=cv2.INTER_AREA).astype(np.int16)


def decode(path):
    out = {"opened": False, "packets": 0, "packet_times": [], "corrupt_packets": [], "frames": [],
           "errors": [], "stream": None}
    try:
        container = av.open(str(path))
    except av.error.FFmpegError as e:
        out["errors"].append({"kind": "open_failed", "message": str(e)})
        return out
    out["opened"] = True
    if not container.streams.video:
        out["errors"].append({"kind": "no_video_stream", "message": "container has no video stream"})
        container.close()
        return out

    stream = container.streams.video[0]
    stream.thread_type = "NONE"  # single-threaded so each decoder message maps to its packet
    tb = stream.time_base
    out["stream"] = {"time_base": str(tb), "codec": stream.codec_context.name,
                     "average_rate": float(stream.average_rate) if stream.average_rate else None}

    previous = None
    old_level = av.logging.get_level()
    av.logging.set_level(av.logging.WARNING)
    try:
        packets = container.demux(stream)
        while True:
            with av.logging.Capture() as demux_logs:
                try:
                    packet = next(packets)
                except StopIteration:
                    packet = None
                except av.error.FFmpegError as e:  # container damaged mid-stream (e.g. truncation)
                    out["errors"].append({"kind": "demux_error", "message": str(e),
                                          "after_packet": out["packets"]})
                    packet = None
            for level, source, message in demux_logs:  # container-level messages
                out["errors"].append({"kind": "demux_message", "level": LEVELS.get(level, str(level)),
                                      "source": source, "message": message.strip(),
                                      "after_packet": out["packets"]})
            if packet is None:
                break
            packet_time = float(packet.pts * tb) if packet.pts is not None else None
            if packet.size:
                out["packets"] += 1
                if packet_time is not None:
                    out["packet_times"].append(packet_time)
                if packet.is_corrupt:
                    out["corrupt_packets"].append(packet_time)
            with av.logging.Capture() as logs:
                try:
                    frames = packet.decode()
                except av.error.FFmpegError as e:
                    out["errors"].append({"kind": "decode_exception", "message": str(e),
                                          "packet_time_s": packet_time})
                    frames = []
            for level, source, message in logs:
                out["errors"].append({"kind": "decoder_message", "level": LEVELS.get(level, str(level)),
                                      "source": source, "message": message.strip(),
                                      "packet_time_s": packet_time})
            for frame in frames:
                thumb = _thumb(frame)
                diff = None if previous is None else float(np.abs(thumb - previous).mean())
                previous = thumb
                out["frames"].append({
                    "pts_s": float(frame.pts * tb) if frame.pts is not None else None,
                    "key": bool(frame.key_frame),
                    "type": frame.pict_type.name if hasattr(frame.pict_type, "name") else str(frame.pict_type),
                    "corrupt": bool(frame.is_corrupt),
                    "diff_prev": diff,
                })
    finally:
        av.logging.set_level(old_level)
        container.close()
    return out
