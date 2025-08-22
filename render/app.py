from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
import uuid
import socket
import asyncio
from playwright.async_api import async_playwright
import shutil
from contextlib import asynccontextmanager

OUTPUT_DIR = Path("cards")
OUTPUT_DIR.mkdir(exist_ok=True)

HOST_IP = socket.gethostbyname(socket.gethostname())
PORT = 8001

# 生命周期管理，退出时清理缓存
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # 删除 cards 目录下的所有文件
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
        OUTPUT_DIR.mkdir(exist_ok=True)
        print("✅ 已清理 cards 缓存目录")

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

app.mount("/cards", StaticFiles(directory=OUTPUT_DIR), name="cards")

FONT_PATH = "C:/Windows/Fonts/simhei.ttf"

class PaperCardRequest(BaseModel):
    title: str
    abstract: str

async def generate_paper_card_html_png(title, abstract, output_dir=OUTPUT_DIR, scale=3):
    output_dir.mkdir(exist_ok=True)
    width, height = 600, 800
    filename = f"{uuid.uuid4().hex}.png"
    output_path = output_dir / filename

    html_content = f"""
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{
                margin: 0;
                padding: 0;
                background-color: #F5F6FA;
                font-family: "SimHei", sans-serif;
            }}
            .card {{
                width: {width}px;
                height: {height}px;
                padding: 40px;
                box-sizing: border-box;
                background-color: white;
                position: relative;
                transform: scale({scale});
                transform-origin: top left;
            }}
            .bar {{
                width: 15%;
                height: 10px;
                background-color: black;
                position: absolute;
                top: 30px;
                left: 40px;
            }}
            .title {{
                font-size: 28px;
                font-weight: bold;
                margin-top: 60px;
                text-align: justify;
                text-justify: inter-word;
                word-wrap: break-word;
            }}
            .abstract {{
                font-size: 18px;
                color: dimgray;
                margin-top: 20px;
                text-align: justify;
                text-justify: inter-word;
                word-wrap: break-word;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="bar"></div>
            <div class="title">{title}</div>
            <div class="abstract">{abstract}</div>
        </div>
    </body>
    </html>
    """

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": width*scale, "height": height*scale})
        await page.set_content(html_content, wait_until="networkidle")
        await page.screenshot(path=str(output_path), full_page=False)
        await browser.close()

    return output_path

@app.post("/render_card")
async def render_card(req: PaperCardRequest):
    png_path = await generate_paper_card_html_png(req.title, req.abstract)
    return JSONResponse({
        "url": f"http://{HOST_IP}:{PORT}/cards/{png_path.name}"
    })
