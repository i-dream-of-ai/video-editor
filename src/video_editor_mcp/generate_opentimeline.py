import opentimelineio as otio
import opentimelineio.opentime as otio_time
from videojungle import ApiClient
import os
import sys
import json
import argparse
import logging
import subprocess

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
    track = otio.schema.Track(name=edit_spec["name"])
    timeline.tracks.append(track)

    for cut in edit_spec["video_series_sequential"]:
        # TODO: fix with asset call too
        video = vj.video_files.get(cut["video_id"])
        local_file = os.path.join(download_dir, f"{video.name}.mp4")
        os.makedirs(download_dir, exist_ok=True)

        if not video.download_url:
            logging.info(f"Skipping video {video.id} - no download URL provided")
            continue

        # Check if file already exists
        if os.path.exists(local_file):
            logging.info(f"Video already exists at {local_file}, skipping download")
            lf = local_file
        else:
            lf = vj.video_files.download(video.id, local_file)
            logging.info(f"Downloaded video to {lf}")

        fps = video.fps if video.fps else 24.0
        start_time = create_rational_time(cut["video_start_time"], fps)
        end_time = create_rational_time(cut["video_end_time"], fps)
        # print(lf)

        clip = otio.schema.Clip(
            name=f"clip_{edit_spec['name']}",
            media_reference=otio.schema.ExternalReference(
                target_url=os.path.abspath(local_file)
            ),
            source_range=otio.opentime.TimeRange(start_time, (end_time - start_time)),
        )
        track.append(clip)

    otio.adapters.write_to_file(timeline, filename)
    logging.info(f"OTIO timeline saved to {filename}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="JSON file path")
    parser.add_argument("--output", help="Output file path")
    parser.add_argument("--json", type=json.loads, help="JSON string")

    args = parser.parse_args()
    spec = None
    # Set DaVinci Resolve environment variables
    os.environ["RESOLVE_SCRIPT_API"] = (
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
    )
    os.environ["RESOLVE_SCRIPT_LIB"] = (
        "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
    )

    # Add Resolve's Python modules to the path
    script_module_path = os.path.join(os.environ["RESOLVE_SCRIPT_API"], "Modules")
    if script_module_path not in sys.path:
        sys.path.append(script_module_path)

    # Now import DaVinciResolveScript
    try:
        import DaVinciResolveScript as dvr_script
    except ImportError as e:
        # print(f"Error importing DaVinciResolveScript: {e}")
        # print("Make sure DaVinci Resolve is installed correctly.")
        # Re-raise the exception or set dvr_script to None as a fallback
        dvr_script = None

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
    create_otio_timeline(spec, output_file)
    output_file_absolute = os.path.abspath(output_file)
    if dvr_script:
        resolve = dvr_script.scriptapp("Resolve")
        if resolve:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()
            media_pool = project.GetMediaPool()
            media_pool.ImportTimelineFromFile(
                output_file_absolute, {"timelineName": spec["name"]}
            )
            logging.info(f"Imported {output_file} into DaVinci Resolve")
        else:
            logging.error("Could not connect to DaVinci Resolve.")
