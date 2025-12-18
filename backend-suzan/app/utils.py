import os
from datetime import datetime
from .config import settings

UPLOAD_DIR = getattr(settings, "UPLOAD_DIR", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

async def save_upload_file(upload_file):
    """
    Saves file asynchronously to prevent blocking.
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    clean_filename = upload_file.filename.replace(" ", "_")
    filename = f"{timestamp}_{clean_filename}"
    path = os.path.join(UPLOAD_DIR, filename)

    # Use await read() so other requests can proceed
    content = await upload_file.read()

    with open(path, "wb") as f:
        f.write(content)

    return path