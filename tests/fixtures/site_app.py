from __future__ import annotations

from html import escape
from urllib.parse import parse_qs

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

app = FastAPI()
items: list[str] = []
scenario = "default"


@app.post("/__reset")
def reset() -> dict[str, int]:
    global scenario
    items.clear()
    scenario = "default"
    return {"items": 0}


@app.post("/__prepare")
async def prepare(request: Request) -> dict[str, object]:
    global scenario
    payload = await request.json()
    scenario = str(payload.get("scenario", "default"))
    inputs = payload.get("inputs", {})
    if scenario == "existing-item":
        seed = inputs.get("seed", "Seed item") if isinstance(inputs, dict) else "Seed item"
        items.append(str(seed))
    return {"application_version": "fixture-v1", "scenario": scenario, "items": list(items)}


@app.get("/__state")
def state() -> dict[str, object]:
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
      <a href="/validation">Validation</a>
      <a href="/items/edit">Edit item</a>
      <a href="/items/delete">Delete item</a>
      <a href="/search">Search</a>
      <a href="/dialog">Dialog</a>
      <a href="/tabs">Tabs</a>
      <a href="/admin">Admin</a>
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


@app.get("/validation", response_class=HTMLResponse)
def validation() -> str:
    return """
    <html><head><title>Validation</title></head><body>
      <form action="/validation" method="post" novalidate>
        <label for="required-name">Required name</label>
        <input id="required-name" name="name">
        <button type="submit">Validate</button>
      </form>
    </body></html>
    """


@app.post("/validation", response_class=HTMLResponse)
async def validate_item(request: Request) -> str:
    form = parse_qs((await request.body()).decode("utf-8"))
    name = form.get("name", [""])[0]
    if not name:
        return (
            "<html><head><title>Validation</title></head><body><div role='alert'>Name is required</div></body></html>"
        )
    return "<html><head><title>Valid</title></head><body><h1>Valid</h1></body></html>"


@app.get("/items/edit", response_class=HTMLResponse)
def edit_form() -> str:
    current = items[0] if items else ""
    return f"""
    <html><head><title>Edit item</title></head><body>
      <form action="/items/edit" method="post">
        <label for="edit-name">Item name</label>
        <input id="edit-name" name="name" value="{escape(current)}">
        <button type="submit">Save</button>
      </form>
    </body></html>
    """


@app.post("/items/edit", response_class=HTMLResponse)
async def edit_item(request: Request) -> str:
    form = parse_qs((await request.body()).decode("utf-8"))
    name = form.get("name", [""])[0]
    if items:
        items[0] = name
    return f"<html><head><title>Updated</title></head><body><h1>Updated</h1><p>{escape(name)}</p></body></html>"


@app.get("/items/delete", response_class=HTMLResponse)
def delete_form() -> str:
    current = items[0] if items else "No item"
    return f"""
    <html><head><title>Delete item</title></head><body>
      <p>{escape(current)}</p>
      <form action="/items/delete" method="post"><button type="submit">Delete</button></form>
    </body></html>
    """


@app.post("/items/delete", response_class=HTMLResponse)
def delete_item() -> str:
    items.clear()
    return "<html><head><title>Deleted</title></head><body><h1>Deleted</h1></body></html>"


@app.get("/search", response_class=HTMLResponse)
def search(request: Request) -> str:
    query = request.query_params.get("q", "")
    results = [item for item in items if query.casefold() in item.casefold()]
    rendered = "".join(f"<li>{escape(item)}</li>" for item in results)
    return f"""
    <html><head><title>Search</title></head><body>
      <form><label for="query">Search items</label><input id="query" name="q" value="{escape(query)}">
      <button type="submit">Search</button></form><ul>{rendered}</ul>
    </body></html>
    """


@app.get("/dialog", response_class=HTMLResponse)
def dialog() -> str:
    return """
    <html><head><title>Dialog</title></head><body>
      <button onclick="document.getElementById('help').showModal()">Open help</button>
      <dialog id="help"><h2>Dialog content</h2><button onclick="this.closest('dialog').close()">Close</button></dialog>
    </body></html>
    """


@app.get("/tabs", response_class=HTMLResponse)
def tabs() -> str:
    return """
    <html><head><title>Tabs</title></head><body>
      <div role="tablist">
        <button role="tab" aria-selected="true" aria-controls="overview">Overview</button>
        <button role="tab" aria-selected="false" aria-controls="settings"
          onclick="document.querySelectorAll('[role=tab]').forEach(x => x.setAttribute('aria-selected','false'));
                   this.setAttribute('aria-selected','true');
                   document.getElementById('overview').hidden=true;
                   document.getElementById('settings').hidden=false">Settings</button>
      </div>
      <section id="overview" role="tabpanel">Overview panel</section>
      <section id="settings" role="tabpanel" hidden>Settings panel</section>
    </body></html>
    """


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request) -> str:
    if request.cookies.get("fixture_role") != "admin":
        return "<html><head><title>Access denied</title></head><body><h1>Access denied</h1></body></html>"
    return "<html><head><title>Admin</title></head><body><h1>Admin console</h1></body></html>"


@app.get("/external-redirect")
def external_redirect() -> RedirectResponse:
    return RedirectResponse("https://outside.example/redirected", status_code=302)


@app.post("/items", response_class=HTMLResponse)
async def create_item(request: Request) -> str:
    form = parse_qs((await request.body()).decode("utf-8"))
    name = form.get("name", [""])[0]
    if scenario == "save-failure":
        return """
        <html><head><title>Save failed</title></head><body>
          <div role="status">Success</div><div role="alert">Save failed</div>
        </body></html>
        """
    items.append(name)
    return f"""
    <!doctype html>
    <html><head><title>Created</title></head>
    <body><h1>Created</h1><p>{escape(name)}</p><a href="/">Back to items</a></body></html>
    """
