from __future__ import annotations

from html import escape
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI()
items: list[str] = []


@app.post("/__reset")
def reset() -> dict[str, int]:
    items.clear()
    return {"items": 0}


@app.get("/__state")
def state() -> dict[str, list[str]]:
    return {"items": list(items)}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    rendered = "".join(f"<li>{item}</li>" for item in items)
    return f"""
    <!doctype html>
    <html><head><title>Fixture</title></head>
    <body>
      <h1>Items</h1>
      <form action="/items" method="post">
        <label for="name">Item name</label>
        <input id="name" name="name" required>
        <button type="submit">Create</button>
      </form>
      <ul>{rendered}</ul>
    </body></html>
    """


@app.post("/items", response_class=HTMLResponse)
async def create_item(request: Request) -> str:
    form = parse_qs((await request.body()).decode("utf-8"))
    name = form.get("name", [""])[0]
    items.append(name)
    return f"""
    <!doctype html>
    <html><head><title>Created</title></head>
    <body><h1>Created</h1><p>{escape(name)}</p><a href="/">Back to items</a></body></html>
    """
