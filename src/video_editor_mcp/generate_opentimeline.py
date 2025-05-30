import opentimelineio as otio
from videojungle import ApiClient
import os
import sys
import json
import argparse
import logging
import requests

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


def download_asset(asset_id, asset_type, download_dir="downloads"):
    """Download an asset using either the assets API or video files API based on type"""
    try:
        # Determine which API to use based on asset type
        if asset_type in ["user", "audio", "mp3", "wav", "aac", "m4a"]:
            # Use assets API for user uploads and audio files
            asset = vj.assets.get(asset_id)
            if not asset.download_url:
                logging.error(f"No download URL for asset {asset_id}")
                return None
            download_url = asset.download_url
            filename = (
                asset.name if hasattr(asset, "name") and asset.name else str(asset_id)
            )
        else:
            # Use video files API for video files
            video = vj.video_files.get(asset_id)
            if not video.download_url:
                logging.error(f"No download URL for video {asset_id}")
                return None
            download_url = video.download_url
            filename = (
                video.name if hasattr(video, "name") and video.name else str(asset_id)
            )

        # Determine file extension based on asset type
        ext_map = {
            "mp3": ".mp3",
            "wav": ".wav",
            "aac": ".aac",
            "m4a": ".m4a",
            "user": ".mp4",  # Default for user videos
            "video": ".mp4",
            "audio": ".mp3",  # Default for generic audio
        }
        ext = ext_map.get(asset_type, ".mp4")

        # Remove any existing extension and add the correct one
        if "." in filename:
            filename = filename.rsplit(".", 1)[0]
        local_file = os.path.join(download_dir, f"{filename}{ext}")

        # Check if file already exists
        if os.path.exists(local_file):
            logging.info(f"Asset already exists at {local_file}, skipping download")
            return local_file

        # Download the file
        if asset_type in ["user", "audio", "mp3", "wav", "aac", "m4a"]:
            # Use requests for assets API downloads
            response = requests.get(download_url, stream=True)
            response.raise_for_status()

            with open(local_file, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        else:
            # Use video files download method
            lf = vj.video_files.download(asset_id, local_file)
            logging.info(f"Downloaded video to {lf}")
            return lf

        logging.info(f"Downloaded asset {asset_id} to {local_file}")
        return local_file

    except Exception as e:
        logging.error(f"Error downloading asset {asset_id}: {e}")
        return None


def create_otio_timeline(
    edit_spec, filename, download_dir="downloads"
) -> otio.schema.Timeline:
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)

    timeline = otio.schema.Timeline(name=edit_spec.get("name", "Timeline"))

    # Create video track
    video_track = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    timeline.tracks.append(video_track)

    # Create audio track if there are audio overlays
    audio_track = None
    if "audio_overlay" in edit_spec and edit_spec["audio_overlay"]:
        audio_track = otio.schema.Track(name="A1", kind=otio.schema.TrackKind.Audio)
        timeline.tracks.append(audio_track)

    # Process video clips
    for cut in edit_spec["video_series_sequential"]:
        asset_type = cut.get("type", "video")
        local_file = download_asset(cut["video_id"], asset_type, download_dir)

        if not local_file:
            continue

        fps = edit_spec.get("video_output_fps", 24.0)
        start_time = create_rational_time(cut["video_start_time"], fps)
        end_time = create_rational_time(cut["video_end_time"], fps)

        clip = otio.schema.Clip(
            name=f"clip_{cut['video_id']}",
            media_reference=otio.schema.ExternalReference(
                target_url=os.path.abspath(local_file)
            ),
            source_range=otio.opentime.TimeRange(start_time, (end_time - start_time)),
        )

        # TODO: Add audio level metadata if needed
        if "audio_levels" in cut and cut["audio_levels"]:
            # OpenTimelineIO doesn't have direct audio level support
            # This would need to be handled in the editing software
            clip.metadata["audio_levels"] = cut["audio_levels"]

        video_track.append(clip)

    # Process audio overlays
    if audio_track and "audio_overlay" in edit_spec:
        for audio_item in edit_spec["audio_overlay"]:
            audio_type = audio_item.get("type", "mp3")
            local_audio_file = download_asset(
                audio_item["audio_id"], audio_type, download_dir
            )

            if not local_audio_file:
                continue

            fps = edit_spec.get("video_output_fps", 24.0)
            audio_start = create_rational_time(audio_item["audio_start_time"], fps)
            audio_end = create_rational_time(audio_item["audio_end_time"], fps)

            audio_clip = otio.schema.Clip(
                name=f"audio_{audio_item['audio_id']}",
                media_reference=otio.schema.ExternalReference(
                    target_url=os.path.abspath(local_audio_file)
                ),
                source_range=otio.opentime.TimeRange(
                    audio_start, (audio_end - audio_start)
                ),
            )

            # Add audio level metadata if present
            if "audio_levels" in audio_item and audio_item["audio_levels"]:
                audio_clip.metadata["audio_levels"] = audio_item["audio_levels"]

            audio_track.append(audio_clip)

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
    except ImportError:
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
