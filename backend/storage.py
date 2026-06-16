import os
import re
import uuid
from pathlib import Path


UPLOAD_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "outputs",
    "uploads",
)

ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}


def _safe_filename(filename: str) -> str:
    name = Path(filename or "upload").name
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def _ensure_upload_dir() -> None:
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def save_upload(file_bytes: bytes, filename: str) -> str:
    """
    Saves an uploaded source file and returns a file_id.

    Uploads are retained by default for MVP debugging/reuse. cleanup_upload()
    exists for explicit deletion or a later retention policy.
    """
    if not file_bytes:
        raise ValueError("Uploaded file is empty.")

    safe_name = _safe_filename(filename)
    extension = Path(safe_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError(
            "Unsupported file type. Please upload .xlsx, .xls, or .csv."
        )

    _ensure_upload_dir()
    file_id = str(uuid.uuid4())
    path = os.path.join(UPLOAD_DIR, f"{file_id}__{safe_name}")

    with open(path, "wb") as handle:
        handle.write(file_bytes)

    return file_id


def get_upload_path(file_id: str) -> str:
    _ensure_upload_dir()
    prefix = f"{file_id}__"

    for filename in os.listdir(UPLOAD_DIR):
        if filename.startswith(prefix):
            path = os.path.join(UPLOAD_DIR, filename)
            if os.path.isfile(path):
                return path

    raise FileNotFoundError(f"No uploaded file found for file_id '{file_id}'.")


def cleanup_upload(file_id: str) -> None:
    path = get_upload_path(file_id)
    os.remove(path)
