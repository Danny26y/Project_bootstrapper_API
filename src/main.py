from fastapi import FastAPI, HTTPException, Header, Depends, Request, BackgroundTasks
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from typing import Optional, List
import os

from db import init_pool
from services import (
    create_user, get_user_by_api_key, ensure_usage_row,
    increment_call_and_check_limit, increment_project_and_check_limit,
    create_preset, list_presets, get_preset, update_preset, delete_preset
)
from utils import create_zip_archive, ALLOWED_FREE_TEMPLATES, generate_api_key
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_pool()
    yield

app = FastAPI(title="Project Bootstrapper API (Free Tier)", lifespan=lifespan)

# read limits from env
DAILY_LIMIT = int(os.getenv('API_RATE_LIMIT_PER_DAY', '10'))
MONTH_LIMIT = int(os.getenv('API_PROJECTS_PER_MONTH', '5'))


# ---- request models ----
class UserCreate(BaseModel):
    username: str = Field(..., max_length=50)
    email: str


class PresetIn(BaseModel):
    name: str
    template: str
    git_init: Optional[bool] = False
    use_venv: Optional[bool] = False
    license_type: Optional[str] = None


class CreateRequest(BaseModel):
    name: str
    template: str
    git_init: Optional[bool] = False
    use_venv: Optional[bool] = False
    license_type: Optional[str] = None


# ---- dependencies ----
@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <html>
    <head>
        <title>Project Bootstrapper API — Quickstart</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; line-height: 1.6; }
            code { background-color: #f4f4f4; padding: 2px 4px; border-radius: 4px; }
            pre { background-color: #f4f4f4; padding: 10px; border-radius: 6px; overflow-x: auto; }
            h1, h2 { color: #333; }
        </style>
    </head>
    <body>
        <h1>🚀 Project Bootstrapper API — Quickstart</h1>
        <p>Welcome! Follow these steps to get started with the free tier.</p>

        <h2>1️⃣ Register & Get API Key</h2>
        <pre>
POST https://projectbootstrapperapi-production.up.railway.app/users
Content-Type: application/json

{
    "username": "yourname",
    "email": "you@example.com"
}
        </pre>
        <p>The response will include your <code>api_key</code> — save it.</p>

        <h2>2️⃣ List Templates</h2>
        <pre>
GET https://projectbootstrapperapi-production.up.railway.app/templates
Headers:
X-API-Key: YOUR_API_KEY
        </pre>

        <h2>3️⃣ Create & Download a Project</h2>
        <pre>
POST https://projectbootstrapperapi-production.up.railway.app/create-and-download
Headers:
X-API-Key: YOUR_API_KEY
Content-Type: application/json

{
    "name": "myproject",
    "template": "flask"
}
        </pre>
        <p>This will download <code>myproject.zip</code> with your generated project.</p>

        <h2>ℹ️ Free Tier Limits</h2>
        <ul>
            <li>10 API calls/day</li>
            <li>5 projects/month</li>
            <li>Templates: flask, fastapi, basic-python</li>
        </ul>

        <p>📚 For full docs, visit <a href="/docs">Swagger UI</a>.</p>
    </body>
    </html>
    """

def require_api_key(x_api_key: Optional[str] = Header(None)):
    if not x_api_key:
        raise HTTPException(status_code=401, detail='Missing X-API-Key header')
    user = get_user_by_api_key(x_api_key)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid API key')
    # enforce daily call limit
    ok = increment_call_and_check_limit(user['id'], DAILY_LIMIT)
    if not ok:
        raise HTTPException(status_code=429, detail='Daily API call limit exceeded')
    return user


# ---- endpoints ----
@app.post('/users', response_model=dict)
def register_user(payload: UserCreate):
    # create user and generate API key
    api_key = generate_api_key()
    try:
        user = create_user(payload.username, payload.email, api_key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {k: user[k] for k in user}


@app.get('/templates')
def list_templates(user=Depends(require_api_key)):
    # only free templates available
    return {'available_templates': list(ALLOWED_FREE_TEMPLATES)}


@app.post('/presets')
def add_preset(p: PresetIn, user=Depends(require_api_key)):
    if p.template not in ALLOWED_FREE_TEMPLATES:
        raise HTTPException(status_code=403, detail='Template not allowed for free tier')
    created = create_preset(user['id'], p.name, p.template, p.git_init, p.use_venv, p.license_type)
    return created


@app.get('/presets')
def get_presets(user=Depends(require_api_key)):
    return list_presets(user['id'])


@app.put('/presets/{preset_id}')
def put_preset(preset_id: int, payload: PresetIn, user=Depends(require_api_key)):
    if payload.template not in ALLOWED_FREE_TEMPLATES:
        raise HTTPException(status_code=403, detail='Template not allowed for free tier')
    updated = update_preset(user['id'], preset_id, payload.dict())
    if not updated:
        raise HTTPException(status_code=404, detail='Preset not found')
    return updated


@app.delete('/presets/{preset_id}')
def remove_preset(preset_id: int, user=Depends(require_api_key)):
    ok = delete_preset(user['id'], preset_id)
    if not ok:
        raise HTTPException(status_code=404, detail='Preset not found')
    return {'deleted': True}


@app.post('/create')
def create_project(req: CreateRequest, download: Optional[bool] = False, background_tasks: BackgroundTasks = None, user=Depends(require_api_key)):
    # template check
    if req.template not in ALLOWED_FREE_TEMPLATES:
        raise HTTPException(status_code=403, detail='Template not allowed for free tier')
    # check monthly project limit
    ok = increment_project_and_check_limit(user['id'], MONTH_LIMIT)
    if not ok:
        raise HTTPException(status_code=429, detail='Monthly project limit exceeded')

    # create project folder in tmp
    import tempfile, pathlib
    project_root = pathlib.Path(tempfile.mkdtemp(prefix='proj_'))
    try:
        # write basic files according to template
        if req.template == 'basic-python':
            (project_root / req.name).mkdir(parents=True, exist_ok=True)
            (project_root / req.name / '__init__.py').write_text('')
            (project_root / 'README.md').write_text(f"# {req.name}\nGenerated by bootstrapper\n")
            (project_root / 'main.py').write_text('print("Hello from generated project")')
        elif req.template == 'flask':
            (project_root / req.name).mkdir(parents=True, exist_ok=True)
            (project_root / req.name / 'app.py').write_text('from flask import Flask\napp = Flask(__name__)\n\n@app.route("/")\ndef home():\n    return "Hello, Flask!"\n')
            (project_root / 'requirements.txt').write_text('flask')
        elif req.template == 'fastapi':
            (project_root / 'app').mkdir(parents=True, exist_ok=True)
            (project_root / 'app' / 'main.py').write_text('from fastapi import FastAPI\napp=FastAPI()\n@app.get("/")\ndef root():\n    return {"msg":"Hello FastAPI"}')
            (project_root / 'requirements.txt').write_text('fastapi\nuvicorn')
        # optional git init / venv flags are ignored for free tier (blocked features)

        if download:
            data = create_zip_archive(str(project_root))
            return Response(content=data, media_type='application/zip', headers={
                'Content-Disposition': f'attachment; filename="{req.name}.zip"'
            })
        else:
            # return a simple manifest
            files = [str(p.relative_to(project_root)) for p in project_root.rglob('*') if p.is_file()]
            return {'project_name': req.name, 'files': files}
    finally:
        # cleanup
        import shutil
        try:
            shutil.rmtree(project_root)
        except Exception:
            pass


@app.post('/create-and-download')
def create_and_download(req: CreateRequest, user=Depends(require_api_key)):
    # convenience wrapper
    return create_project(req, download=True, user=user)


@app.get('/health')
def health():
    return {'status': 'ok'}
