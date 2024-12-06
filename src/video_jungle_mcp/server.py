import asyncio

from videojungle import ApiClient
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
from pydantic import AnyUrl
import mcp.server.stdio
import sys

VJ_API_KEY = sys.argv[1]

if not VJ_API_KEY:
    raise Exception("VJ_API_KEY environment variable is required")

vj = ApiClient(VJ_API_KEY)

server = Server("video-jungle-mcp")

tools = ["add-video", "search-videos"]

@server.list_resources()
async def handle_list_resources() -> list[types.Resource]:
    """
    List available video files.
    Each video files is available at a specific url
    """
    videos = vj.video_files.list()
    #projects = vj.projects.list()

    videos = [
        types.Resource(
            uri=AnyUrl(f"vj://video-file/{video.id}"),
            name=f"Video Jungle Video: {video.name}",
            description=f"User provided description: {video.description}",
            mimeType="video/mp4",
        )
        for video in videos
    ]

    '''
    projects = [
        types.Resource(
            uri=AnyUrl(f"vj://project/{project.id}"),
            name=f"Video Jungle Project: {project.name}",
            description=f"Project description: {project.description}",
            mimeType="application/json",
        )
        for project in projects
    ]'''

    return videos # + projects


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
        id = id.lstrip("/video-file/")
        video = vj.video_files.get(id)
        return video.model_dump_json()
    raise ValueError(f"Video not found: {id}")

@server.list_prompts()
async def handle_list_prompts() -> list[types.Prompt]:
    """
    List available prompts.
    Each prompt can have optional arguments to customize its behavior.
    """
    return [
        types.Prompt(
            name="summarize-notes",
            description="Creates a summary of all notes",
            arguments=[
                types.PromptArgument(
                    name="style",
                    description="Style of the summary (brief/detailed)",
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
    if name != "summarize-notes":
        raise ValueError(f"Unknown prompt: {name}")

    style = (arguments or {}).get("style", "brief")
    detail_prompt = " Give extensive details." if style == "detailed" else ""

    return types.GetPromptResult(
        description="Summarize the current notes",
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(
                    type="text",
                    text=f"Here are the current notes to summarize:{detail_prompt}\n\n"
                    + "\n".join(
                        f"- {name}: {content}"
                        for name, content in notes.items()
                    ),
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
    return [
        types.Tool(
            name="add-video",
            description="Upload video from URL",
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
            name="search-videos",
            description="Search videos by query",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="generate-edit-from-videos",
            description="Generate an edit from videos",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "resolution": {"type": "string"},
                    "edit": {"type": "array", "cuts": {"video_id": "string",
                                                       "start_time": "string",
                                                       "end_time": "string",}},
                },
                "required": ["edit", "project_id"],
            },
        ),
        types.Tool(
            name="generate-edit-from-single-video",
            description="Generate a video edit from a single video",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "resolution": {"type": "string"},
                    "video_id": {"type": ""},
                    "edit": {"type": "array", "cuts": {
                                                       "start_time": "string",
                                                       "end_time": "string",}
                                                       },
                },
                "required": ["edit", "project_id", "video_id"],
            },
        ),
    ]

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
    
    if name == "add-video" and arguments:
        name = arguments.get("name")
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
    if name == "search-videos" and arguments:
        query = arguments.get("query")

        if not query:
            raise ValueError("Missing query")

        videos = vj.video_files.search(query)
        return [
            types.TextContent(
                type="text",
                text="Videos:\n" + "\n".join(f"- {video['video']['name']} at vj://video-file/{video['video_id']} \n - URL to view video: {video['video']['url']} \n - Scene changes in video: {video['scene_changes']} \n - Video    manuscript: {video['script']}" for video in videos),
            )
        ]
    if name == "generate-edit-from-videos" and arguments:
        edit = arguments.get("edit")
        project = arguments.get("project_id")
        resolution = arguments.get("resolution")
        created = False

        if not edit:
            raise ValueError("Missing edit")
        if not project:
            raise ValueError("Missing project")
        if not resolution:
            resolution = "1080x1920"
        
        updated_edit = [{**cut, "type": "videofile", 
                        "audio_levels": [{
                         "audio_level": "0.5",
                         "start_time": cut["start_time"],
                         "end_time": cut["end_time"],}]
                         } for cut in edit]

        json_edit = {
            "video_edit_version": "1.0",
            "video_output_format": "mp4",
            "video_output_resolution": resolution,
            "video_output_fps": 30.0,
            "video_output_filename": "output_video.mp4",
            "video_series_sequential": updated_edit
        }

        try: 
            proj = vj.projects.get(project)
        except Exception as e:
            proj = vj.projects.create(name=project, description=f"Claude generated project")
            project = proj.id
            created = True

        edit = vj.projects.render_edit(project, json_edit)

        if created:
            # we created a new project so let the user / LLM know
            return [
                types.TextContent(
                    type="text",
                    text=f"Created new project {proj.name} and created edit {edit['id']} with raw edit info: {updated_edit}"
                )
            ]
        
        return [
            types.TextContent(
                type="text",
                text=f"Generated edit in existing project {proj.name} with id: {edit['id']} and raw edit info: {updated_edit}",
            )
        ]
    if name == "generate-edit-from-single-video" and arguments:
        edit = arguments.get("edit")
        project = arguments.get("project_id")
        video_id = arguments.get("video_id")

        resolution = arguments.get("resolution")
        created = False 


        if not edit:
            raise ValueError("Missing edit")
        if not project:
            raise ValueError("Missing project")
        if not video_id:
            raise ValueError("Missing video_id")
        if not resolution:
            resolution = "1080x1920"
        
        updated_edit = [{**cut, "video_id": video_id,
                        "type": "videofile", 
                        "audio_levels": [{
                         "audio_level": "0.5",
                         "start_time": cut["start_time"],
                         "end_time": cut["end_time"],}]
                         } for cut in edit]

        json_edit = {
            "video_edit_version": "1.0",
            "video_output_format": "mp4",
            "video_output_resolution": resolution,
            "video_output_fps": 30.0,
            "video_output_filename": "output_video.mp4",
            "video_series_sequential": updated_edit
        }

        try: 
            proj = vj.projects.get(project)
        except Exception as e:
            proj = vj.projects.create(name=project, description=f"Claude generated project")
            project = proj.id
            created = True

        edit = vj.projects.render_edit(project, json_edit)

        if created:
            # we created a new project so let the user / LLM know
            return [
                types.TextContent(
                    type="text",
                    text=f"Created new project {proj.name} and created edit {edit['id']} with raw edit info: {updated_edit}"
                )
            ]

        return [
            types.TextContent(
                type="text",
                text=f"Generated edit in project {proj.name} with id: {edit['id']} and raw edit info: {updated_edit}",
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