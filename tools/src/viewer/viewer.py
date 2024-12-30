import logging
import os
import subprocess
import sys

from videojungle import ApiClient

# Configure the logging
logging.basicConfig(
    filename="app.log",  # Name of the log file
    level=logging.INFO,  # Log level (e.g., DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format="%(asctime)s - %(levelname)s - %(message)s",  # Log format
)

if os.environ.get("VJ_API_KEY"):
    VJ_API_KEY = os.environ.get("VJ_API_KEY")
else:
    try:
        VJ_API_KEY = sys.argv[1]
    except Exception:
        logging.error("no API key provided")
        VJ_API_KEY = None

if VJ_API_KEY is None:
    raise Exception("API key not found")

if len(sys.argv) < 4:
    logging.info(f"called with {sys.argv}")
    raise Exception("Usage: viewer.py <asset_id> <output_file> <video name>")

vj = ApiClient(VJ_API_KEY)

logging.info(f"Downloading asset {sys.argv[1]} to {sys.argv[2]}")
final = vj.assets.download(sys.argv[1], sys.argv[2])
logging.info(f"Asset downloaded to {final}")

logging.info(f"Playing video {sys.argv[3]}")
subprocess.call(["../video-player/vj-player", sys.argv[3], sys.argv[2]])
