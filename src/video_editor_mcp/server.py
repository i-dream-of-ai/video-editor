import logging
import os
import subprocess
import sys
import threading
import time
from typing import List, Optional, Union, Any, Dict
import json
import webbrowser
import uuid

import mcp.server.stdio
import mcp.types as types
import osxphotos
import requests
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from pydantic import AnyUrl

from transformers import AutoModel
from videojungle import ApiClient, VideoFilters

from .search_local_videos import get_videos_by_keyword
from .generate_charts import render_bar_chart
from .generate_opentimeline import create_otio_timeline

import numpy as np


if os.environ.get("VJ_API_KEY"):
    VJ_API_KEY = os.environ.get("VJ_API_KEY")
else:
    try:
        VJ_API_KEY = sys.argv[1]
    except Exception:
        VJ_API_KEY = None

BROWSER_OPEN = False
# Configure the logging
logging.basicConfig(
    filename="app.log",  # Name of the log file
    level=logging.INFO,  # Log level (e.g., DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format="%(asctime)s - %(levelname)s - %(message)s",  # Log format
)

if not VJ_API_KEY:
    try:
        with open(".env", "r") as f:
            for line in f:
                if "VJ_API_KEY" in line:
                    VJ_API_KEY = line.split("=")[1]
    except Exception:
        raise Exception(
            "VJ_API_KEY environment variable is required or a .env file with the key is required"
        )
    raise Exception("VJ_API_KEY environment variable is required")

vj = ApiClient(VJ_API_KEY)


class PhotosDBLoader:
    def __init__(self):
        self._db: Optional[osxphotos.PhotosDB] = None
        self.start_loading()

    def start_loading(self):
        def load():
            self._db = osxphotos.PhotosDB()
            logging.info("PhotosDB loaded")

        thread = threading.Thread(target=load)
        thread.daemon = True  # Make thread exit when main program exits
        thread.start()

    @property
    def db(self) -> osxphotos.PhotosDB:
        if self._db is None:
            raise Exception("PhotosDB still loading")
        return self._db


class EmbeddingModelLoader:
    def __init__(self, model_name: str = "jinaai/jina-clip-v1"):
        self._model: Optional[AutoModel] = None
        self.model_name = model_name
        self.start_loading()

    def start_loading(self):
        def load():
            self._model = AutoModel.from_pretrained(
                self.model_name, trust_remote_code=True
            )
            logging.info(f"Model {self.model_name} loaded")

        thread = threading.Thread(target=load)
        thread.daemon = True
        thread.start()

    @property
    def model(self) -> AutoModel:
        if self._model is None:
            raise Exception(f"Model {self.model_name} still loading")
        return self._model

    def encode_text(
        self,
        texts: Union[str, List[str]],
        truncate_dim: Optional[int] = None,
        task: Optional[str] = None,
    ) -> dict:
        """
        Encode text and format the embeddings in the expected JSON structure
        """
        embeddings = self.model.encode_text(texts, truncate_dim=truncate_dim, task=task)

        # Format the response in the expected structure
        return {"embeddings": embeddings.tolist(), "embedding_type": "text_embeddings"}

    def encode_image(
        self, images: Union[str, List[str]], truncate_dim: Optional[int] = None
    ) -> dict:
        """
        Encode images and format the embeddings in the expected JSON structure
        """
        embeddings = self.model.encode_image(images, truncate_dim=truncate_dim)

        return {"embeddings": embeddings.tolist(), "embedding_type": "image_embeddings"}

    def post_embeddings(
        self, embeddings: dict, endpoint_url: str, headers: Optional[dict] = None
    ) -> requests.Response:
        """
        Post embeddings to the specified endpoint
        """
        if headers is None:
            headers = {"Content-Type": "application/json"}

        response = requests.post(endpoint_url, json=embeddings, headers=headers)
        response.raise_for_status()
        return response


# Create global loader instance, (requires access to host computer!)
if sys.platform == "darwin" and os.environ.get("LOAD_PHOTOS_DB"):
    photos_loader = PhotosDBLoader()

model_loader = EmbeddingModelLoader()

server = Server("video-jungle-mcp")

try:
    # videos_at_start = vj.video_files.list()
    projects_at_start = vj.projects.list()
except Exception as e:
    logging.error(f"Error getting projects at start: {e}")
    videos_at_start = []

counter = 10

# Cache for pagination with timestamps for cleanup
_search_result_cache: Dict[str, Dict] = {}
_CACHE_TTL = 60 * 4  # 4 minute cache TTL


# Function to clean old cache entries
def cleanup_cache():
    """Remove cache entries older than TTL."""
    current_time = time.time()
    keys_to_remove = []

    for key, cache_entry in _search_result_cache.items():
        if current_time - cache_entry["timestamp"] > _CACHE_TTL:
            keys_to_remove.append(key)

    for key in keys_to_remove:
        del _search_result_cache[key]

    if keys_to_remove:
        logging.info(f"Cleaned up {len(keys_to_remove)} expired search caches")


tools = [
    "add-video",
    "search-local-videos",
    "search-remote-videos",
    "generate-edit-from-videos",
    "create-videojungle-project",
    "create-video-bar-chart-from-two-axis-data",
    "create-video-line-chart-from-two-axis-data",
    "edit-locally",
    "generate-edit-from-single-video",
    "update-video-edit",
]


def validate_y_values(y_values: Any) -> bool:
    """
    Validates that y_values is a single-dimensional array/list of numbers.

    Args:
        y_values: The input to validate

    Returns:
        bool: True if validation passes

    Raises:
        ValueError: If validation fails with a descriptive message
    """
    # Check if input is a list or numpy array
    if not isinstance(y_values, (list, np.ndarray)):
        raise ValueError("y_values must be a list")

    # Convert to numpy array for easier handling
    y_array = np.array(y_values)

    # Check if it's multi-dimensional
    if len(y_array.shape) > 1:
        raise ValueError("y_values must be a single-dimensional array")

    # Check if all elements are numeric
    if not np.issubdtype(y_array.dtype, np.number):
        raise ValueError("all elements in y_values must be numbers")

    # Check for NaN or infinite values
    if np.any(np.isnan(y_array)) or np.any(np.isinf(y_array)):
        raise ValueError("y_values cannot contain NaN or infinite values")

    return True


@server.list_resources()
async def handle_list_resources() -> list[types.Resource]:
    """
    List available video files.
    Each video files is available at a specific url
    """
    global counter, projects_at_start
    counter += 1
    # check to see if DaVinci Resolve is open

    # We do this counter because otherwise Claude is very aggressive
    # about requests
    if counter % 100 == 0:
        projects = vj.projects.list()
        projects_at_start = projects
        counter = 0
    """
    videos = [
        types.Resource(
            uri=AnyUrl(f"vj://video-file/{video.id}"),
            name=f"Video Jungle Video: {video.name}",
            description=f"User provided description: {video.description}",
            mimeType="video/mp4",
        )
        for video in videos_at_start
    ]"""

    projects = [
        types.Resource(
            uri=AnyUrl(f"vj://projects/{project.id}"),
            name=f"Video Jungle Project: {project.name}",
            description=f"Project description: {project.description}",
            mimeType="application/json",
        )
        for project in projects_at_start
    ]

    return projects  # videos  # + projects


@server.read_resource()
async def handle_read_resource(uri: AnyUrl) -> str:
    """
    Read a video's content by its URI.
    The video id is extracted from the URI host component.
    """
    if uri.scheme != "vj":
        raise ValueError(f"Unsupported URI scheme: {uri.scheme}")

    id = uri.path
    if id is not None:
        id = id.lstrip("/projects/")
        proj = vj.projects.get(id)
        logging.info(f"project is: {proj}")
        return proj.model_dump_json()
    raise ValueError(f"Project not found: {id}")


@server.list_prompts()
async def handle_list_prompts() -> list[types.Prompt]:
    """
    List available prompts.
    Each prompt can have optional arguments to customize its behavior.
    """
    return [
        types.Prompt(
            name="generate-local-search",
            description="Generate a local search for videos using appropriate label names from the Photos app.",
            arguments=[
                types.PromptArgument(
                    name="search_query",
                    description="Natural language query to be translated into Photos app label names.",
                    required=False,
                )
            ],
        )
    ]


@server.get_prompt()
async def handle_get_prompt(
    name: str, arguments: dict[str, str] | None
) -> types.GetPromptResult:
    """
    Generate a prompt by combining arguments with server state.
    The prompt includes all current notes and can be customized via arguments.
    """
    if name != "generate-local-search":
        raise ValueError(f"Unknown prompt: {name}")

    if not arguments:
        raise ValueError("Missing arguments")

    search_query = arguments.get("search_query")
    if not search_query:
        raise ValueError("Missing search_query")

    return types.GetPromptResult(
        description="Generate a local search for videos using appropriate label names from the Photos app.",
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(
                    type="text",
                    text=f"Here are the exact label names you need to match in your query:\n\n For the specific query: {search_query}, you should use the following labels: {photos_loader.db.labels_as_dict} for the search-local-videos tool",
                ),
            )
        ],
    )


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """
    List available tools.
    Each tool specifies its arguments using JSON Schema validation.
    """
    if os.environ.get("LOAD_PHOTOS_DB"):
        return [
            types.Tool(
                name="create-videojungle-project",
                description="Create a new Video Jungle project to create video edits, add videos, assets, and more.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name of the project",
                        },
                        "description": {
                            "type": "string",
                            "description": "Description of the project",
                        },
                    },
                },
            ),
            types.Tool(
                name="edit-locally",
                description="Create an OpenTimelineIO file for local editing with the user's desktop video editing suite.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "edit_id": {
                            "type": "string",
                            "description": "UUID of the edit to download",
                        },
                        "project_id": {
                            "type": "string",
                            "description": "UUID of the project the video edit lives within",
                        },
                    },
                    "required": ["edit_id", "project_id"],
                },
            ),
            types.Tool(
                name="add-video",
                description="Upload video from URL. Begins analysis of video to allow for later information retrieval for automatic video editing an search.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "url": {"type": "string"},
                    },
                    "required": ["name", "url"],
                },
            ),
            types.Tool(
                name="search-remote-videos",
                description="Default method to search videos. Will return videos including video_ids, which allow for information retrieval and building video edits. For large result sets, you can paginate through chunks using search_id and page parameters.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Text search query"},
                        "limit": {
                            "type": "integer",
                            "default": 10,
                            "minimum": 1,
                            "description": "Maximum number of results to return per page",
                        },
                        "project_id": {
                            "type": "string",
                            "format": "uuid",
                            "description": "Project ID to scope the search",
                        },
                        "duration_min": {
                            "type": "number",
                            "minimum": 0,
                            "description": "Minimum video duration in seconds",
                        },
                        "duration_max": {
                            "type": "number",
                            "minimum": 0,
                            "description": "Maximum video duration in seconds",
                        },
                        "search_id": {
                            "type": "string",
                            "description": "ID of a previous search to continue pagination. If provided, returns the next chunk of results",
                        },
                        "page": {
                            "type": "integer",
                            "default": 1,
                            "minimum": 1,
                            "description": "Page number to retrieve when paginating through results",
                        },
                        "items_per_page": {
                            "type": "integer",
                            "default": 5,
                            "minimum": 1,
                            "maximum": 20,
                            "description": "Number of items to show per page when paginating",
                        },
                    },
                    "created_after": {
                        "type": "string",
                        "format": "date-time",
                        "description": "Filter videos created after this datetime",
                    },
                    "created_before": {
                        "type": "string",
                        "format": "date-time",
                        "description": "Filter videos created before this datetime",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "uniqueItems": True,
                        "description": "Set of tags to filter by",
                    },
                    "include_segments": {
                        "type": "boolean",
                        "default": True,
                        "description": "Whether to include video segments in results",
                    },
                    "include_related": {
                        "type": "boolean",
                        "default": False,
                        "description": "Whether to include related videos",
                    },
                    "query_audio": {
                        "type": "string",
                        "description": "Audio search query",
                    },
                    "query_img": {
                        "type": "string",
                        "description": "Image search query",
                    },
                },
            ),
            types.Tool(
                name="search-local-videos",
                description="Search user's local videos in Photos app by keyword",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string"},
                        "start_date": {
                            "type": "string",
                            "description": "ISO 8601 formatted datetime string (e.g. 2024-01-21T15:30:00Z)",
                        },
                        "end_date": {
                            "type": "string",
                            "description": "ISO 8601 formatted datetime string (e.g. 2024-01-21T15:30:00Z)",
                        },
                    },
                    "required": ["keyword"],
                },
            ),
            types.Tool(
                name="generate-edit-from-videos",
                description="Generate an edit from videos, from within a specific project. Creates a new project to work within no existing project ID (UUID) is passed ",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project_id": {
                            "type": "string",
                            "description": "Either an existing Project UUID or String. A UUID puts the edit in an existing project, and a string creates a new project with that name.",
                        },
                        "name": {"type": "string", "description": "Video Edit name"},
                        "open_editor": {
                            "type": "boolean",
                            "description": "Open a live editor with the project's edit",
                        },
                        "resolution": {
                            "type": "string",
                            "description": "Video resolution. Examples include '1920x1080', '1280x720'",
                        },
                        "edit": {
                            "type": "array",
                            "cuts": {
                                "video_id": {
                                    "type": "string",
                                    "description": "Video UUID",
                                },
                                "video_start_time": {
                                    "type": "string",
                                    "description": "Clip start time in 00:00:00.000 format",
                                },
                                "video_end_time": {
                                    "type": "string",
                                    "description": "Clip end time in 00:00:00.000 format",
                                },
                            },
                        },
                    },
                    "required": ["edit", "cuts", "name", "project_id"],
                },
            ),
            types.Tool(
                name="generate-edit-from-single-video",
                description="Generate a compressed video edit from a single video.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string"},
                        "resolution": {"type": "string"},
                        "video_id": {"type": "string"},
                        "edit": {
                            "type": "array",
                            "cuts": {
                                "video_start_time": "time",
                                "video_end_time": "time",
                            },
                        },
                    },
                    "required": ["edit", "project_id", "video_id", "cuts"],
                },
            ),
            types.Tool(
                name="update-video-edit",
                description="Update an existing video edit within a specific project.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project_id": {
                            "type": "string",
                            "description": "UUID of the project containing the edit",
                        },
                        "edit_id": {
                            "type": "string",
                            "description": "UUID of the video edit to update",
                        },
                        "name": {"type": "string", "description": "Video Edit name"},
                        "description": {
                            "type": "string",
                            "description": "Description of the video edit",
                        },
                        "video_output_format": {
                            "type": "string",
                            "description": "Output format for the video (e.g., 'mp4', 'webm')",
                        },
                        "video_output_resolution": {
                            "type": "string",
                            "description": "Video resolution. Examples include '1920x1080', '1280x720'",
                        },
                        "video_output_fps": {
                            "type": "number",
                            "description": "Frames per second for the output video",
                        },
                        "video_series_sequential": {
                            "type": "array",
                            "description": "Array of video clips in sequential order",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "video_id": {
                                        "type": "string",
                                        "description": "Video UUID",
                                    },
                                    "video_start_time": {
                                        "type": "string",
                                        "description": "Clip start time in 00:00:00.000 format",
                                    },
                                    "video_end_time": {
                                        "type": "string",
                                        "description": "Clip end time in 00:00:00.000 format",
                                    },
                                },
                            },
                        },
                        "audio_overlay": {
                            "type": "object",
                            "description": "Audio overlay settings and assets",
                        },
                        "rendered": {
                            "type": "boolean",
                            "description": "Whether the edit has been rendered",
                        },
                    },
                    "required": ["project_id", "edit_id"],
                },
            ),
            types.Tool(
                name="create-video-bar-chart-from-two-axis-data",
                description="Create a video bar chart from two-axis data",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "x_values": {"type": "array", "items": {"type": "string"}},
                        "y_values": {"type": "array", "items": {"type": "number"}},
                        "x_label": {"type": "string"},
                        "y_label": {"type": "string"},
                        "title": {"type": "string"},
                        "filename": {"type": "string"},
                    },
                    "required": ["x_values", "y_values", "x_label", "y_label", "title"],
                },
            ),
            types.Tool(
                name="create-video-line-chart-from-two-axis-data",
                description="Create a video line chart from two-axis data",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "x_values": {"type": "array", "items": {"type": "string"}},
                        "y_values": {"type": "array", "items": {"type": "number"}},
                        "x_label": {"type": "string"},
                        "y_label": {"type": "string"},
                        "title": {"type": "string"},
                        "filename": {"type": "string"},
                    },
                    "required": ["x_values", "y_values", "x_label", "y_label", "title"],
                },
            ),
        ]
    return [
        types.Tool(
            name="create-videojungle-project",
            description="Create a new Video Jungle project to create video edits, add videos, assets, and more.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the project"},
                    "description": {
                        "type": "string",
                        "description": "Description of the project",
                    },
                },
            },
        ),
        types.Tool(
            name="edit-locally",
            description="Create an OpenTimelineIO file for local editing with the user's desktop video editing suite.",
            inputSchema={
                "type": "object",
                "properties": {
                    "edit_id": {
                        "type": "string",
                        "description": "UUID of the edit to download",
                    },
                    "project_id": {
                        "type": "string",
                        "description": "UUID of the project the video edit lives within",
                    },
                },
                "required": ["edit_id", "project_id"],
            },
        ),
        types.Tool(
            name="add-video",
            description="Upload video from URL. Begins analysis of video to allow for later information retrieval for automatic video editing an search.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["name", "url"],
            },
        ),
        types.Tool(
            name="search-remote-videos",
            description="Default method to search videos. Will return videos including video_ids, which allow for information retrieval and building video edits. For large result sets, you can paginate through chunks using search_id and page parameters.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text search query"},
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "minimum": 1,
                        "description": "Maximum number of results to return per page",
                    },
                    "project_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": "Project ID to scope the search",
                    },
                    "duration_min": {
                        "type": "number",
                        "minimum": 0,
                        "description": "Minimum video duration in seconds",
                    },
                    "duration_max": {
                        "type": "number",
                        "minimum": 0,
                        "description": "Maximum video duration in seconds",
                    },
                    "search_id": {
                        "type": "string",
                        "description": "ID of a previous search to continue pagination. If provided, returns the next chunk of results",
                    },
                    "page": {
                        "type": "integer",
                        "default": 1,
                        "minimum": 1,
                        "description": "Page number to retrieve when paginating through results",
                    },
                    "items_per_page": {
                        "type": "integer",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20,
                        "description": "Number of items to show per page when paginating",
                    },
                },
                "created_after": {
                    "type": "string",
                    "format": "date-time",
                    "description": "Filter videos created after this datetime",
                },
                "created_before": {
                    "type": "string",
                    "format": "date-time",
                    "description": "Filter videos created before this datetime",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "uniqueItems": True,
                    "description": "Set of tags to filter by",
                },
                "include_segments": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to include video segments in results",
                },
                "include_related": {
                    "type": "boolean",
                    "default": False,
                    "description": "Whether to include related videos",
                },
                "query_audio": {
                    "type": "string",
                    "description": "Audio search query",
                },
                "query_img": {
                    "type": "string",
                    "description": "Image search query",
                },
            },
        ),
        types.Tool(
            name="generate-edit-from-videos",
            description="Generate an edit from videos, from within a specific project. Creates a new project to work within no existing project ID (UUID) is passed ",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Either an existing Project UUID or String. A UUID puts the edit in an existing project, and a string creates a new project with that name.",
                    },
                    "name": {"type": "string", "description": "Video Edit name"},
                    "open_editor": {
                        "type": "boolean",
                        "description": "Open a live editor with the project's edit",
                    },
                    "resolution": {
                        "type": "string",
                        "description": "Video resolution. Examples include '1920x1080', '1280x720'",
                    },
                    "edit": {
                        "type": "array",
                        "cuts": {
                            "video_id": {"type": "string", "description": "Video UUID"},
                            "video_start_time": {
                                "type": "string",
                                "description": "Clip start time in 00:00:00.000 format",
                            },
                            "video_end_time": {
                                "type": "string",
                                "description": "Clip end time in 00:00:00.000 format",
                            },
                        },
                    },
                },
                "required": ["edit", "cuts", "name", "project_id"],
            },
        ),
        types.Tool(
            name="generate-edit-from-single-video",
            description="Generate a compressed video edit from a single video.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "resolution": {"type": "string"},
                    "video_id": {"type": "string"},
                    "edit": {
                        "type": "array",
                        "cuts": {
                            "video_start_time": "time",
                            "video_end_time": "time",
                        },
                    },
                },
                "required": ["edit", "project_id", "video_id", "cuts"],
            },
        ),
        types.Tool(
            name="update-video-edit",
            description="Update an existing video edit within a specific project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "UUID of the project containing the edit",
                    },
                    "edit_id": {
                        "type": "string",
                        "description": "UUID of the video edit to update",
                    },
                    "name": {"type": "string", "description": "Video Edit name"},
                    "description": {
                        "type": "string",
                        "description": "Description of the video edit",
                    },
                    "video_output_format": {
                        "type": "string",
                        "description": "Output format for the video (e.g., 'mp4', 'webm')",
                    },
                    "video_output_resolution": {
                        "type": "string",
                        "description": "Video resolution. Examples include '1920x1080', '1280x720'",
                    },
                    "video_output_fps": {
                        "type": "number",
                        "description": "Frames per second for the output video",
                    },
                    "video_series_sequential": {
                        "type": "array",
                        "description": "Array of video clips in sequential order",
                        "items": {
                            "type": "object",
                            "properties": {
                                "video_id": {
                                    "type": "string",
                                    "description": "Video UUID",
                                },
                                "video_start_time": {
                                    "type": "string",
                                    "description": "Clip start time in 00:00:00.000 format",
                                },
                                "video_end_time": {
                                    "type": "string",
                                    "description": "Clip end time in 00:00:00.000 format",
                                },
                            },
                        },
                    },
                    "audio_overlay": {
                        "type": "object",
                        "description": "Audio overlay settings and assets",
                    },
                    "rendered": {
                        "type": "boolean",
                        "description": "Whether the edit has been rendered",
                    },
                },
                "required": ["project_id", "edit_id"],
            },
        ),
        types.Tool(
            name="create-video-bar-chart-from-two-axis-data",
            description="Create a video bar chart from two-axis data",
            inputSchema={
                "type": "object",
                "properties": {
                    "x_values": {"type": "array", "items": {"type": "string"}},
                    "y_values": {"type": "array", "items": {"type": "number"}},
                    "x_label": {"type": "string"},
                    "y_label": {"type": "string"},
                    "title": {"type": "string"},
                    "filename": {"type": "string"},
                },
                "required": ["x_values", "y_values", "x_label", "y_label", "title"],
            },
        ),
        types.Tool(
            name="create-video-line-chart-from-two-axis-data",
            description="Create a video line chart from two-axis data",
            inputSchema={
                "type": "object",
                "properties": {
                    "x_values": {"type": "array", "items": {"type": "string"}},
                    "y_values": {"type": "array", "items": {"type": "number"}},
                    "x_label": {"type": "string"},
                    "y_label": {"type": "string"},
                    "title": {"type": "string"},
                    "filename": {"type": "string"},
                },
                "required": ["x_values", "y_values", "x_label", "y_label", "title"],
            },
        ),
    ]


def format_single_video(video):
    """
    Format a single video metadata tuple (metadata_dict, confidence_score)
    Returns a formatted string and a Python code string representation
    """
    try:
        # Create human-readable format
        readable_format = f"""
            Video Embedding Result:
            -------------
            Video ID: {video['video_id']}
            Description: {video['description']}
            Timestamp: {video['timepoint']}
            Detected Items: {', '.join(video['detected_items']) if video['detected_items'] else 'None'}
        """
    except Exception as e:
        raise ValueError(f"Error formatting video: {str(e)}")

    return readable_format


def filter_unique_videos_keep_first(json_results):
    seen = set()
    return [
        item
        for item in json_results
        if item["video_id"] not in seen and not seen.add(item["video_id"])
    ]


def format_video_info(video):
    try:
        if video.get("script") is not None:
            if len(video.get("script")) > 200:
                script = video.get("script")[:200] + "..."
            else:
                script = video.get("script")
        else:
            script = "N/A"
        segments = []
        for segment in video.get("matching_segments", []):
            segments.append(
                f"- Time: {segment.get('start_seconds', 'N/A')} to {segment.get('end_seconds', 'N/A')}"
            )
        joined_segments = "\n".join(segments)
        return (
            f"- Video Id: {video.get('video_id', 'N/A')}\n"
            f"  Video name: {video.get('video', {}).get('name', 'N/A')}\n"
            f"  URL to view video: {video.get('video', {}).get('url', 'N/A')}\n"
            f"  Video manuscript: {script}"
            f"  Matching scenes: {joined_segments}"
            f"  Generated description: {video.get('video', 'N/A').get('generated_description', 'N/A')}"
        )
    except Exception as e:
        return f"Error formatting video: {str(e)}"


def format_video_info_long(video):
    try:
        if video.get("script") is not None:
            if len(video.get("script")) > 200:
                script = video.get("script")[:200] + "..."
            else:
                script = video.get("script")
        else:
            script = "N/A"
        return (
            f"- Video Id: {video.get('video_id', 'N/A')}\n"
            f"  Video name: {video.get('video', {}).get('name', 'N/A')}\n"
            f"  URL to view video: {video.get('video', {}).get('url', 'N/A')}\n"
            f"  Generated description: {video.get('video', 'N/A').get('generated_description', 'N/A')}"
            f"  Video manuscript: {script}"
            f"  Matching times: {video.get('scene_changes', 'N/A')}"
        )
    except Exception as e:
        return f"Error formatting video: {str(e)}"


@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """
    Handle tool execution requests.
    Tools can modify server state and notify clients of changes.
    """
    if name not in tools:
        raise ValueError(f"Unknown tool: {name}")

    if not arguments:
        raise ValueError("Missing arguments")

    # Store some tool results in server state for pagination
    global _search_result_cache

    if name == "create-videojungle-project" and arguments:
        namez = arguments.get("name")
        description = arguments.get("description")

        if not namez or not description:
            raise ValueError("Missing project name")

        # Create a new project
        project = vj.projects.create(name=namez, description=description)

        # Notify clients that resources have changed
        await server.request_context.session.send_resource_list_changed()

        return [
            types.TextContent(
                type="text",
                text=f"Created new project '{project.name}' with id '{project.id}'",
            )
        ]

    if name == "edit-locally" and arguments:
        project_id = arguments.get("project_id")
        edit_id = arguments.get("edit_id")

        if not project_id or not edit_id:
            raise ValueError("Missing edit and / or  project id")
        env_vars = {"VJ_API_KEY": VJ_API_KEY, "PATH": os.environ["PATH"]}
        edit_data = vj.projects.get_edit(project_id, edit_id)
        formatted_name = edit_data["name"].replace(" ", "-")
        with open(f"{formatted_name}.json", "w") as f:
            json.dump(edit_data, f, indent=4)
        logging.info(f"edit data is: {edit_data}")
        logging.info(f"current directory is: {os.getcwd()}")
        subprocess.Popen(
            [
                "uv",
                "run",
                "python",
                "./src/video_editor_mcp/generate_opentimeline.py",
                "--file",
                f"{formatted_name}.json",
                "--output",
                f"{formatted_name}.otio",
            ],
            env=env_vars,
        )

        return [
            types.TextContent(
                type="text",
                text=f"Edit {edit_data['name']} is being downloaded and converted to OpenTimelineIO format. You can find it in the current directory.",
            )
        ]

    if name == "add-video" and arguments:
        name = arguments.get("name")  # type: ignore
        url = arguments.get("url")

        if not name or not url:
            raise ValueError("Missing name or content")

        # Update server state
        vj.video_files.create(name=name, filename=str(url), upload_method="url")

        # Notify clients that resources have changed
        await server.request_context.session.send_resource_list_changed()
        return [
            types.TextContent(
                type="text",
                text=f"Added video '{name}' with url: {url}",
            )
        ]
    if name == "search-remote-videos" and arguments:
        # Check if this is a pagination request
        search_id = arguments.get("search_id")
        page = arguments.get("page", 1)
        items_per_page = arguments.get("items_per_page", 5)

        # Run cache cleanup
        cleanup_cache()

        # If we have a search_id, we're doing pagination
        if search_id and search_id in _search_result_cache:
            cache_entry = _search_result_cache[search_id]
            cached_results = cache_entry["results"]
            total_items = len(cached_results)
            total_pages = (total_items + items_per_page - 1) // items_per_page

            # Update timestamp on access
            _search_result_cache[search_id]["timestamp"] = time.time()

            start_idx = (page - 1) * items_per_page
            end_idx = min(start_idx + items_per_page, total_items)

            # Get current page items
            current_page_items = cached_results[start_idx:end_idx]

            # Format the paginated results
            query_info = cache_entry.get("query", "unknown")
            response_text = []
            response_text.append(
                f"Search Results for '{query_info}' (Page {page}/{total_pages}, showing items {start_idx+1}-{end_idx} of {total_items})"
            )

            # Add embedding note if it exists in the cache
            embedding_note = cache_entry.get("embedding_note")
            if embedding_note:
                response_text.append(embedding_note)

            # Format each item based on whether it's a regular result or an embedding result
            if len(current_page_items) > 0:
                if (
                    isinstance(current_page_items[0], dict)
                    and "video_id" in current_page_items[0]
                ):
                    response_text.extend(
                        format_video_info(video) for video in current_page_items
                    )
                else:
                    response_text.extend(current_page_items)
            else:
                response_text.append("No items to display on this page.")

            # Add pagination info with navigation options
            pagination_info = []
            if page > 1:
                pagination_info.append(
                    f"Previous page: call search-remote-videos with search_id='{search_id}' and page={page-1}"
                )

            has_more = page < total_pages
            if has_more:
                pagination_info.append(
                    f"Next page: call search-remote-videos with search_id='{search_id}' and page={page+1}"
                )

            if pagination_info:
                response_text.append("\nNavigation options:")
                response_text.extend(pagination_info)

            if not has_more:
                response_text.append("\nEnd of results.")

            return [
                types.TextContent(
                    type="text",
                    text="\n".join(response_text),
                )
            ]

        # This is a new search request
        query = arguments.get("query")
        limit = arguments.get("limit", 10)
        project_id = arguments.get("project_id")
        tags = arguments.get("tags", None)
        duration_min = arguments.get("duration_min", None)
        duration_max = arguments.get("duration_max", None)
        created_after = arguments.get("created_after", None)
        created_before = arguments.get("created_before", None)
        include_segments = arguments.get("include_segments", True)
        include_related = arguments.get("include_related", False)

        # Validate that at least one query type is provided
        if not query and not tags:
            raise ValueError("At least one query or tag must be provided")

        # Perform the main search with all parameters
        if tags:
            search_params = {
                "limit": limit,
                "include_segments": include_segments,
                "include_related": include_related,
                "tags": json.loads(tags),
                "duration_min": duration_min,
                "duration_max": duration_max,
                "created_after": created_after,
                "created_before": created_before,
            }
        else:
            search_params = {
                "limit": limit,
                "include_segments": include_segments,
                "include_related": include_related,
                "duration_min": duration_min,
                "duration_max": duration_max,
                "created_after": created_after,
                "created_before": created_before,
            }

        # Add optional parameters
        if query:
            search_params["query"] = query
        if project_id:
            search_params["project_id"] = project_id

        embedding_results = []
        embedding_search_formatted = []
        embedding_note = None

        # If we have a text query, try embedding search but fallback to regular search if model is still loading
        if query:
            try:
                embeddings = model_loader.encode_text(query)
                response = model_loader.post_embeddings(
                    embeddings,
                    "https://api.video-jungle.com/video-file/embedding-search",
                    headers={
                        "Content-Type": "application/json",
                        "X-API-KEY": VJ_API_KEY,
                    },
                )

                logging.info(f"Response is: {response.json()}")
                if response.status_code != 200:
                    raise RuntimeError(f"Error searching for videos: {response.text}")

                embedding_results = response.json()
                embedding_search_formatted = [
                    format_single_video(video) for video in embedding_results
                ]
            except Exception as e:
                if "still loading" in str(e):
                    logging.warning(
                        "Embedding model still loading, falling back to text-only search"
                    )
                    embedding_results = []
                    embedding_search_formatted = []
                    # Add note that will be displayed to the user
                    embedding_note = "Note: Embedding-based semantic search is still initializing. Only text-based search results are shown. Please try again later for more accurate semantic search results."
                else:
                    # For other errors, log and continue with regular search
                    logging.error(f"Error in embedding search: {e}")
                    embedding_results = []
                    embedding_search_formatted = []

        # Get regular search results
        videos = vj.video_files.search(**search_params)
        logging.info(f"num videos are: {len(videos)}")

        # If only a few results, return them directly without pagination
        if len(videos) <= 3 and len(videos) >= 1 and not embedding_results:
            return [
                types.TextContent(
                    type="text",
                    text=format_video_info_long(video),
                )
                for video in videos
            ]

        # For larger result sets, set up pagination
        formatted_videos = [format_video_info(video) for video in videos]

        # Store the results in the cache for pagination
        new_search_id = str(uuid.uuid4())

        all_results = []
        if query and embedding_results:
            # Store both types of results
            all_results = formatted_videos + embedding_search_formatted
        else:
            all_results = formatted_videos

        # Store results with timestamp and embedding note if present
        _search_result_cache[new_search_id] = {
            "results": all_results,
            "timestamp": time.time(),
            "query": query or "tag-search",
            "embedding_note": embedding_note,
        }

        # Calculate pagination info
        total_items = len(all_results)
        total_pages = (total_items + items_per_page - 1) // items_per_page

        # Format the first page results
        response_text = []
        query_display = query or "tag search"
        response_text.append(
            f"Search Results for '{query_display}' (Page 1/{total_pages}, showing items 1-{min(items_per_page, total_items)} of {total_items})"
        )

        # Add note about embedding search if it was skipped due to model loading
        if embedding_note:
            response_text.append(embedding_note)

        # Show first page items
        first_page_items = all_results[:items_per_page]
        if first_page_items:
            response_text.extend(first_page_items)
        else:
            response_text.append("No results found matching your query.")

        # Add pagination info
        has_more = total_pages > 1
        if has_more:
            response_text.append(f"\nNavigation options:")
            response_text.append(
                f"Next page: call search-remote-videos with search_id='{new_search_id}' and page=2"
            )
            response_text.append(
                f"\nTip: You can control items per page with the items_per_page parameter (default: 5, max: 20)"
            )
        else:
            response_text.append("\nEnd of results.")

        return [
            types.TextContent(
                type="text",
                text="\n".join(response_text),
            )
        ]

    if name == "search-local-videos" and arguments:
        if not os.environ.get("LOAD_PHOTOS_DB"):
            raise ValueError(
                "You must set the LOAD_PHOTOS_DB environment variable to True to use this tool"
            )

        keyword = arguments.get("keyword")
        if not keyword:
            raise ValueError("Missing keyword")
        start_date = None
        end_date = None

        if arguments.get("start_date") and arguments.get("end_date"):
            start_date = arguments.get("start_date")
            end_date = arguments.get("end_date")

        try:
            db = photos_loader.db
            videos = get_videos_by_keyword(db, keyword, start_date, end_date)
            return [
                types.TextContent(
                    type="text",
                    text=(
                        f"Number of Videos Returned: {len(videos)}. Here are the first 100 results: \n{videos[:100]}"
                    ),
                )
            ]
        except Exception:
            raise RuntimeError("Local Photos database not yet initialized")

    if name == "generate-edit-from-videos" and arguments:
        edit = arguments.get("edit")
        project = arguments.get("project_id")
        name = arguments.get("name")  # type: ignore
        open_editor = arguments.get("open_editor")
        resolution = arguments.get("resolution")
        created = False

        logging.info(f"edit is: {edit} and the type is: {type(edit)}")
        if open_editor is None:
            open_editor = True

        if not edit:
            raise ValueError("Missing edit")
        if not project:
            raise ValueError("Missing project")
        if not resolution:
            resolution = "1080x1920"
        if not name:
            raise ValueError("Missing name for edit")
        if resolution == "1080p":
            resolution = "1920x1080"
        elif resolution == "720p":
            resolution = "1280x720"

        try:
            w, h = resolution.split("x")
            _ = f"{int(w)}x{int(w)}"
        except Exception as e:
            raise ValueError(
                f"Resolution must be in the format 'widthxheight' where width and height are integers: {e}"
            )

        updated_edit = [
            {
                "video_id": cut["video_id"],
                "video_start_time": cut["video_start_time"],
                "video_end_time": cut["video_end_time"],
                "type": "videofile",
                "audio_levels": [
                    {
                        "audio_level": 0.5,
                        "start_time": cut["video_start_time"],
                        "end_time": cut["video_end_time"],
                    }
                ],
            }
            for cut in edit
        ]

        logging.info(f"updated edit is: {updated_edit}")

        json_edit = {
            "video_edit_version": "1.0",
            "video_output_format": "mp4",
            "video_output_resolution": resolution,
            "video_output_fps": 60.0,
            "name": name,
            "video_output_filename": "output_video.mp4",
            "audio_overlay": [],  # TODO: add this back in
            "video_series_sequential": updated_edit,
            "skip_rendering": True,
        }

        try:
            proj = vj.projects.get(project)
        except Exception as e:
            logging.info(f"project not found, creating new project because {e}")
            proj = vj.projects.create(
                name=project, description="Claude generated project"
            )
            project = proj.id
            created = True

        logging.info(f"video edit is: {json_edit}")

        edit = vj.projects.render_edit(project, json_edit)

        webbrowser.open(
            f"https://app.video-jungle.com/projects/{proj.id}/edits/{edit['edit_id']}"
        )
        global BROWSER_OPEN
        BROWSER_OPEN = True
        # the following generates an edit for opentimeline, allowing you to open it in
        # a desktop video editor like final cut pro, etc.
        """
        try:
            original_dir = os.getcwd()
            os.chdir("./tools")
            logging.info(f"in directory: {os.getcwd()}")
            # don't block, because this might take a while
            env_vars = {"VJ_API_KEY": VJ_API_KEY, "PATH": os.environ["PATH"]}
            logging.info(
                f"launching viewer with: {edit['asset_id']} {project}.mp4 {proj.name}"
            )
            subprocess.Popen(
                [
                    "uv",
                    "run",
                    "viewer",
                    edit["asset_id"],
                    f"video-edit-{project}.mp4",
                    proj.name,
                ],
                env=env_vars,
            )
            os.chdir(original_dir)
        except Exception as e:
            logging.info(f"Error running viewer: {e}")
        """
        if created:
            # we created a new project so let the user / LLM know
            return [
                types.TextContent(
                    type="text",
                    text=f"Created new project {proj.name} with id '{proj.id}' and created edit {edit} with raw edit info: {updated_edit}",
                )
            ]

        return [
            types.TextContent(
                type="text",
                text=f"Generated edit in existing project {proj.name} with id '{proj.id}' with generated asset info: {edit} and raw edit info: {updated_edit}",
            )
        ]

    if name == "generate-edit-from-single-video" and arguments:
        edit = arguments.get("edit")
        project = arguments.get("project_id")
        video_id = arguments.get("video_id")

        resolution = arguments.get("resolution")
        created = False

        logging.info(f"edit is: {edit} and the type is: {type(edit)}")

        if not edit:
            raise ValueError("Missing edit")
        if not project:
            raise ValueError("Missing project")
        if not video_id:
            raise ValueError("Missing video_id")
        if not resolution:
            resolution = "1080x1920"

        try:
            w, h = resolution.split("x")
            _ = f"{int(w)}x{int(w)}"
        except Exception as e:
            raise ValueError(
                f"Resolution must be in the format 'widthxheight' where width and height are integers: {e}"
            )

        try:
            updated_edit = [
                {
                    "video_id": video_id,
                    "video_start_time": cut["video_start_time"],
                    "video_end_time": cut["video_end_time"],
                    "type": "video-file",
                    "audio_levels": [],
                }
                for cut in edit
            ]
        except Exception as e:
            raise ValueError(f"Error updating edit: {e}")

        logging.info(f"updated edit is: {updated_edit}")

        json_edit = {
            "video_edit_version": "1.0",
            "video_output_format": "mp4",
            "video_output_resolution": resolution,
            "video_output_fps": 60.0,
            "video_output_filename": "output_video.mp4",
            "audio_overlay": [],  # TODO: add this back in
            "video_series_sequential": updated_edit,
        }

        try:
            proj = vj.projects.get(project)
        except Exception:
            proj = vj.projects.create(
                name=project, description="Claude generated project"
            )
            project = proj.id
            created = True

        logging.info(f"video edit is: {json_edit}")
        try:
            edit = vj.projects.render_edit(project, json_edit)
        except Exception as e:
            logging.error(f"Error rendering edit: {e}")
        logging.info(f"edit is: {edit}")
        try:
            os.chdir("./tools")
            logging.info(f"in directory: {os.getcwd()}")
            # don't block, because this might take a while
            env_vars = {"VJ_API_KEY": VJ_API_KEY, "PATH": os.environ["PATH"]}
            logging.info(
                f"launching viewer with: {edit['asset_id']} {project}.mp4 {proj.name}"
            )
            subprocess.Popen(
                [
                    "uv",
                    "run",
                    "viewer",
                    edit["asset_id"],
                    f"video-edit-{project}.mp4",
                    proj.name,
                ],
                env=env_vars,
            )
        except Exception as e:
            logging.info(f"Error running viewer: {e}")
        if created:
            # we created a new project so let the user / LLM know
            logging.info(f"created new project {proj.name} and created edit {edit}")
            return [
                types.TextContent(
                    type="text",
                    text=f"Created new project {proj.name} with project id '{proj.id}' and raw edit info: {edit}",
                )
            ]

        return [
            types.TextContent(
                type="text",
                text=f"Generated edit in project {proj.name} with project id '{proj.id}' and raw edit info: {edit}",
            )
        ]

    if name == "update-video-edit" and arguments:
        project_id = arguments.get("project_id")
        edit_id = arguments.get("edit_id")
        edit_name = arguments.get("name")
        description = arguments.get("description")
        video_output_format = arguments.get("video_output_format")
        video_output_resolution = arguments.get("video_output_resolution")
        video_output_fps = arguments.get("video_output_fps")
        video_series_sequential = arguments.get("video_series_sequential")
        audio_overlay = arguments.get("audio_overlay")
        rendered = arguments.get("rendered")

        # Validate required parameters
        if not project_id:
            raise ValueError("Missing project_id")
        if not edit_id:
            raise ValueError("Missing edit_id")

        # Process resolution format like in create function
        if video_output_resolution:
            if video_output_resolution == "1080p":
                video_output_resolution = "1920x1080"
            elif video_output_resolution == "720p":
                video_output_resolution = "1280x720"

            # Validate resolution format
            try:
                w, h = video_output_resolution.split("x")
                _ = f"{int(w)}x{int(h)}"
            except Exception as e:
                raise ValueError(
                    f"Resolution must be in the format 'widthxheight' where width and height are integers: {e}"
                )

        # Try to get the existing project
        try:
            proj = vj.projects.get(project_id)
        except Exception as e:
            raise ValueError(f"Project with ID {project_id} not found: {e}")

        # Try to get the existing edit
        try:
            existing_edit = vj.projects.get_edit(project_id, edit_id)
        except Exception as e:
            raise ValueError(
                f"Edit with ID {edit_id} not found in project {project_id}: {e}"
            )

        # Process video clips if provided
        updated_video_series = None
        if video_series_sequential:
            updated_video_series = [
                {
                    "video_id": clip["video_id"],
                    "video_start_time": clip["video_start_time"],
                    "video_end_time": clip["video_end_time"],
                    "type": "videofile",
                    "audio_levels": [
                        {
                            "audio_level": 0.5,
                            "start_time": clip["video_start_time"],
                            "end_time": clip["video_end_time"],
                        }
                    ],
                }
                for clip in video_series_sequential
            ]

        # Create an empty dictionary without type annotations
        update_json = dict()

        # Add fields one by one with explicit type handling
        update_json["video_edit_version"] = "1.0"

        if edit_name:
            update_json["name"] = edit_name
        if description:
            update_json["description"] = description
        if video_output_format:
            update_json["video_output_format"] = video_output_format
        if video_output_resolution:
            update_json["video_output_resolution"] = video_output_resolution
        if video_output_fps is not None:
            update_json["video_output_fps"] = float(video_output_fps)
        if updated_video_series is not None:
            # Cast to a list to ensure proper typing
            update_json["video_series_sequential"] = list(updated_video_series)
        if audio_overlay is not None:
            # Cast to a list to ensure proper typing
            update_json["audio_overlay"] = list(audio_overlay) if audio_overlay else []

        # Skip rendering by default like in create function
        update_json["skip_rendering"] = bool(True)

        # If rendering is explicitly requested
        if rendered is True:
            update_json["skip_rendering"] = bool(False)

        logging.info(f"Updating edit {edit_id} with: {update_json}")

        # Call the API to update the edit
        updated_edit = vj.projects.update_edit(project_id, edit_id, update_json)

        # Optionally open the browser to the updated edit
        if not BROWSER_OPEN:
            webbrowser.open(
                f"https://app.video-jungle.com/projects/{project_id}/edits/{edit_id}"
            )

        return [
            types.TextContent(
                type="text",
                text=f"Updated edit {edit_id} in project {proj.name} with changes: {update_json}",
            )
        ]

    if (
        name == "create-video-bar-chart-from-two-axis-data"
        or "create-video-line-chart-from-two-axis-data"
        and arguments
    ):
        x_values = arguments.get("x_values")
        y_values = arguments.get("y_values")
        x_label = arguments.get("x_label")
        y_label = arguments.get("y_label")
        title = arguments.get("title")
        filename = arguments.get("filename")

        if not x_values or not y_values or not x_label or not y_label or not title:
            raise ValueError("Missing required arguments")
        if not filename:
            if name == "create-video-bar-chart-from-two-axis-data":
                filename = "bar_chart.mp4"
            elif name == "create-video-line-chart-from-two-axis-data":
                filename = "line_chart.mp4"
            else:
                raise ValueError("Invalid tool name")

        y_axis_safe = validate_y_values(y_values)
        if not y_axis_safe:
            raise ValueError("Y values are not valid")

        # Render the bar chart
        data = {
            "x_values": x_values,
            "y_values": y_values,
            "x_label": x_label,
            "y_label": y_label,
            "title": title,
            "filename": filename,
        }
        with open("chart_data.json", "w") as f:
            json.dump(data, f, indent=4)

        file_path = os.path.join(os.getcwd(), "media/videos/720p30/", filename)

        if name == "create-video-bar-chart-from-two-axis-data":
            subprocess.Popen(
                [
                    "uv",
                    "run",
                    "src/video_editor_mcp/generate_charts.py",
                    "chart_data.json",
                    "bar",
                ]
            )

            return [
                types.TextContent(
                    type="text",
                    text=f"Bar chart video  generated.\nSaved to {file_path}",
                )
            ]

        elif name == "create-video-line-chart-from-two-axis-data":
            subprocess.Popen(
                [
                    "uv",
                    "run",
                    "src/video_editor_mcp/generate_charts.py",
                    "chart_data.json",
                    "line",
                ]
            )
            return [
                types.TextContent(
                    type="text",
                    text=f"Line chart video  generated.\nSaved to {file_path}",
                )
            ]


async def main():
    # Run the server using stdin/stdout streams
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="video-jungle-mcp",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )
