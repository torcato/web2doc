from __future__ import annotations

from html import escape
from urllib.parse import parse_qs

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

app = FastAPI()
items: list[str] = []


@app.post("/__reset")
def reset() -> dict[str, int]:
    items.clear()
    return {"items": 0}


@app.get("/__state")
def state() -> dict[str, list[str]]:
    return {"items": list(items)}


@app.get("/login/{role}", response_class=HTMLResponse)
def login(role: str, response: Response) -> str:
    response.set_cookie("fixture_role", role, httponly=True, samesite="strict")
    return f"<html><body><h1>Logged in as {escape(role)}</h1></body></html>"


@app.get("/whoami", response_class=HTMLResponse)
def whoami(request: Request) -> str:
    role = request.cookies.get("fixture_role", "anonymous")
    return f"<html><body><h1>Role: {escape(role)}</h1></body></html>"


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
      <a href="/details">View details</a>
      <a href="https://outside.example/" target="_blank">External help</a>
      <a href="/external-redirect">External redirect</a>
      <div id="delayed-container"></div>
      <script>
        setTimeout(() => {{
          const button = document.createElement("button");
          button.textContent = "Delayed action";
          button.addEventListener("click", () => button.textContent = "Delayed complete");
          document.getElementById("delayed-container").appendChild(button);
        }}, 150);
      </script>
      <ul>{rendered}</ul>
    </body></html>
    """


@app.get("/details", response_class=HTMLResponse)
def details() -> str:
    return "<html><head><title>Details</title></head><body><h1>Item details</h1></body></html>"


@app.get("/external-redirect")
def external_redirect() -> RedirectResponse:
    return RedirectResponse("https://outside.example/redirected", status_code=302)


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
