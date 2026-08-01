import tools

class ToolServiceError(Exception):
    """Custom exception for ToolService errors."""
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code

def _run(func, **kwargs):
    """Helper function to run a tool function and handle exceptions."""
    try:
        return func(**kwargs)
    except PermissionError as e:
        raise ToolServiceError(str(e), status_code=403)
    except FileNotFoundError as e:
        raise ToolServiceError(str(e), status_code=404)
    except Exception as e:
        raise ToolServiceError(f"Unexpected error: {e}", status_code=500)
    
def move_file(src, dst):
    """Move a file from src to dst using the tools module."""
    return _run(tools.move_file, src=src, dst=dst)

def create_folder(path):
    """Create a folder at the specified path using the tools module."""
    return _run(tools.create_folder, path=path)

def organize_by_extension(folder="."):
    """Organize files in the specified directory by their extensions using the tools module."""
    return _run(tools.organize_by_extension, folder=folder)

def list_files(path="."):
    """List files in the specified directory using the tools module."""
    return _run(tools.list_files, path=path)

def find_empty_files(folder="."):
    """Find empty files in the specified directory using the tools module."""
    return _run(tools.find_empty_files, folder=folder)
