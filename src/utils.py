import os
import shutil
import tempfile
import zipfile
import uuid
from pathlib import Path

ALLOWED_FREE_TEMPLATES = {'flask', 'fastapi', 'basic-python'}


def create_zip_archive(folder_path: str) -> bytes:
    tmp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    with zipfile.ZipFile(tmp_zip.name, 'w', zipfile.ZIP_DEFLATED) as zf:
        folder_path = Path(folder_path)
        for f in folder_path.rglob('*'):
            if f.is_file():
                # exclude virtualenv and git
                if '.git' in f.parts or 'venv' in f.parts:
                    continue
                arcname = f.relative_to(folder_path)
                zf.write(f, arcname)
    with open(tmp_zip.name, 'rb') as fh:
        data = fh.read()
    os.unlink(tmp_zip.name)
    return data


def generate_api_key() -> str:
    return str(uuid.uuid4())