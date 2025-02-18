import opentimelineio as otio
import opentimelineio.opentime as otio_time
from videojungle import ApiClient
import os
import sys
import json
import argparse
import logging

logging.basicConfig(
    filename="app.log",  # Name of the log file
    level=logging.INFO,  # Log level (e.g., DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format="%(asctime)s - %(levelname)s - %(message)s",  # Log format
)

vj = ApiClient(os.environ.get("VJ_API_KEY"))


def timecode_to_frames(timecode, fps=24.0):
    """
    Convert HH:MM:SS.xxx format to frames, handling variable decimal places
    """
    try:
        parts = timecode.split(":")
        hours = float(parts[0])
        minutes = float(parts[1])
        seconds = float(parts[2])

        total_seconds = hours * 3600 + minutes * 60 + seconds
        return int(total_seconds * fps)
    except (ValueError, IndexError) as e:
        raise ValueError(f"Invalid timecode format: {timecode}") from e


def create_rational_time(timecode, fps=24.0):
    """Create RationalTime object from HH:MM:SS.xxx format"""
    frames = timecode_to_frames(timecode, fps)
    return otio.opentime.RationalTime(frames, fps)


def create_otio_timeline(
    edit_spec, filename, download_dir="downloads"
) -> otio.schema.Timeline:
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
    timeline = otio.schema.Timeline()
    track = otio.schema.Track(name=edit_spec["edit_name"])
    timeline.tracks.append(track)

    for cut in edit_spec["video_series_sequential"]:
        video = vj.video_files.get(cut["video_id"])
        local_file = os.path.join(download_dir, f"{video.name}.mp4")
        os.makedirs(download_dir, exist_ok=True)
        if not video.download_url:
            logging.info(f"Skipping video {video.id} - no download URL provided")
            continue
        lf = vj.video_files.download(video.id, local_file)
        fps = video.fps if video.fps else 24.0
        start_time = create_rational_time(cut["video_start_time"], fps)
        end_time = create_rational_time(cut["video_end_time"], fps)
        # print(lf)
        logging.info(f"Downloaded video to {lf}")
        clip = otio.schema.Clip(
            name=f"clip_{edit_spec['edit_name']}",
            media_reference=otio.schema.ExternalReference(
                target_url=os.path.abspath(local_file)
            ),
            source_range=otio.opentime.TimeRange(start_time, (end_time - start_time)),
        )
        track.append(clip)

    otio.adapters.write_to_file(timeline, filename)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="JSON file path")
    parser.add_argument("--output", help="Output file path")
    parser.add_argument("--json", type=json.loads, help="JSON string")
    args = parser.parse_args()
    spec = None
    if args.json:
        spec = args.json
    elif args.file:
        with open(args.file) as f:
            spec = json.load(f)
    elif not sys.stdin.isatty():  # Check if data is being piped
        spec = json.load(sys.stdin)
    else:
        parser.print_help()
        sys.exit(1)
    if args.output:
        output_file = args.output
    else:
        output_file = "output.otio"
    """
    edit_spec = {
        "edit": [
            {
                "video_id": "86f37f08-98fa-4bb2-bb75-e164276c1933",
                "video_end_time": "00:00:20",
                "video_start_time": "00:00:10",
            },
            {
                "video_id": "814233f0-7a3a-4e40-90e6-f093be4c44b7",
                "video_end_time": "00:00:25",
                "video_start_time": "00:00:15",
            },
            {
                "video_id": "04c78873-5dba-4bbc-8ba0-2f43b57fee4c",
                "video_end_time": "00:00:30",
                "video_start_time": "00:00:20",
            },
            {
                "video_id": "b292d015-230a-42a8-bce7-8fdd0838623d",
                "video_end_time": "00:00:25",
                "video_start_time": "00:00:15",
            },
            {
                "video_id": "928f5627-d20b-49cd-bace-377a528b5486",
                "video_end_time": "00:00:15",
                "video_start_time": "00:00:05",
            },
            {
                "video_id": "52ac445f-cc60-40b3-b228-7d426150fb7e",
                "video_end_time": "00:00:33",
                "video_start_time": "00:00:23",
            },
            {
                "video_id": "424289e9-e2f2-4c2c-9f84-8bef7827470d",
                "video_end_time": "00:00:20",
                "video_start_time": "00:00:10",
            },
            {
                "video_id": "1ab8002b-2a94-4ffe-88f0-2cacb56e3ffe",
                "video_end_time": "00:00:15",
                "video_start_time": "00:00:05",
            },
        ],
        "project_id": "612afec9-bcb2-47ca-807b-756d6e83b4b7",
        "resolution": "1080p",
    }
    """
    create_otio_timeline(spec, output_file)
