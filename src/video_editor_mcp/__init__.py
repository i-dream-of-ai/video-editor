import asyncio
import sys

from . import server


def main():
    """Main entry point for the package."""
    # Check for --help flag
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("""Video Jungle MCP Server

Usage: video-editor-mcp [OPTIONS] API_KEY

A Model Context Protocol server for video editing operations using Video Jungle API.

Arguments:
  API_KEY    Your Video Jungle API key (can also be set via VJ_API_KEY environment variable)

Options:
  --help     Show this help message and exit

Environment Variables:
  VJ_API_KEY        Video Jungle API key (alternative to command line argument)
  LOAD_PHOTOS_DB    Set to 1 to enable Photos database integration

Examples:
  # Run with API key as argument
  video-editor-mcp your-api-key-here
  
  # Run with API key from environment
  export VJ_API_KEY=your-api-key-here
  video-editor-mcp
  
  # Run with Photos database access
  LOAD_PHOTOS_DB=1 video-editor-mcp your-api-key-here

For more information, visit: https://github.com/burningion/video-editing-mcp""")
        sys.exit(0)

    asyncio.run(server.main())


# Optionally expose other important items at package level
__all__ = ["main", "server"]
