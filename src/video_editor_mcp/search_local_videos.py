import osxphotos
import sys

def get_videos_by_keyword(photosdb, keyword):
    # Use only_movies=True instead of is_video=True
    videos = photosdb.query(osxphotos.QueryOptions(label=[keyword], photos=False, movies=True, incloud=True, ignore_case=True))
    
    # Convert to list of dictionaries if needed
    video_data = [video.asdict() for video in videos]
    
    return video_data

def find_and_export_videos(photosdb,keyword, export_path):
    
    videos = photosdb.query(osxphotos.QueryOptions(label=[keyword], photos=False, movies=True, incloud=True, ignore_case=True))
    
    exported_files = []
    for video in videos:
        try:
            exported = video.export(export_path)
            exported_files.extend(exported)
            print(f"Exported {video.filename} to {exported}")
        except Exception as e:
            print(f"Error exporting {video.filename}: {e}")
    
    return exported_files

# Example usage
if __name__ == "__main__":
    '''
    Usage: python search_local_videos.py <keyword>
    '''
    photosdb = osxphotos.PhotosDB()
    videos = get_videos_by_keyword(photosdb, sys.argv[1])
    for video in videos:
        print(f"Found video: {video.get('filename', 'Unknown')}, {video.get('labels', '')}")
        print(f"number of items returned: {len(videos)}")