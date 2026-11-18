#!/usr/bin/env python3
"""Live Notes for a Vibe agent, one command per step. Standard library only.

    python live_notes.py join <agent link>   save the link, show up, publish a first page
    python live_notes.py publish <file>      replace your page with this Markdown file
    python live_notes.py chat <text>         one typed line in the meeting
    python live_notes.py leave               leave, delete the link and state files

Your name is vibe-agent unless LIVE_NOTES_AGENT_NAME says otherwise.
Each command prints what it did.
"""
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request

VIBE = ".vibe"
LINK = os.path.join(VIBE, "agent-link")
STATE = os.path.join(VIBE, "live-notes")  # name, owner key, per-session cursors
OLD = [os.path.join(VIBE, "live-notes.cursor"), os.path.join(VIBE, "live-notes.wakes")]
LOOP = ('cron: action "schedule", interval_seconds 30, prompt "Live Notes meeting\\n'
        'Nothing to do in this turn. Reply with a single dot (.) and nothing else."')
FIRST_PAGE = "# {name}\n\nFollowing this meeting. Say my name to ask me something; my answers appear here.\n"


class Fail(Exception):
    pass


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def name():
    return os.environ.get("LIVE_NOTES_AGENT_NAME") or read(os.path.join(STATE, "name")) or "vibe-agent"


def call(method, link, route, body=None, ctype="application/json", key=None):
    url = link + route + ("&" if "?" in route else "?") + "name=" + name()
    data = body if isinstance(body, bytes) else (None if body is None else json.dumps(body).encode())
    headers = {"content-type": ctype}
    if key:
        headers["X-Agent-Key"] = key
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8")
            return r.status, json.loads(text) if text.strip().startswith("{") else {}, r.headers
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 410):
            raise Fail("the link no longer works (%d): the meeting ended or you were revoked" % e.code)
        return e.code, {"error": e.read().decode("utf-8", "replace")[:200]}, e.headers


def put_page(link, markdown):
    keyfile = os.path.join(STATE, "owner-key")
    key = read(keyfile)
    code, d, h = call("PUT", link, "pages/" + name(), markdown.encode("utf-8"), "text/markdown", key)
    if code == 409:  # our page from an earlier join, key gone: remove it and publish anew
        call("DELETE", link, "pages/" + name())
        code, d, h = call("PUT", link, "pages/" + name(), markdown.encode("utf-8"), "text/markdown")
    if code != 200 and code != 201:
        raise Fail("publish failed (%d): %s" % (code, d.get("error")))
    new = d.get("owner_key") or h.get("X-Agent-Key")
    if new:
        write(keyfile, new)
    warn = d.get("warnings") or []
    return "Published your page, version %s: %s%s" % (
        d.get("version", "?"), d.get("view_url", ""), " Warnings: %s" % warn if warn else "")


def join(link):
    link = link.strip()
    if not re.match(r"^https?://[^/\s]+/a/[A-Za-z0-9]+/?$", link):
        raise Fail("not an agent link (https://HOST/a/CODE/): %s" % link)
    link = link.rstrip("/") + "/"
    code, d, _ = call("GET", link, "feed")
    if code != 200:
        raise Fail("cannot read the meeting (%d): %s" % (code, d.get("error")))
    if d.get("ended_at"):
        raise Fail("this meeting has ended")
    write(LINK, link)
    write(os.path.join(STATE, "name"), name())
    for f in OLD + [os.path.join(STATE, f) for f in os.listdir(STATE) if f.endswith((".cursor", ".wakes"))]:
        if os.path.exists(f):
            os.remove(f)  # start from now
    people = [p.get("name") for p in (d.get("participants") or {}).get("people", [])]
    print("Joined \"%s\" as %s. People here: %s." % (d.get("title"), name(), ", ".join(people) or "none yet"))
    print(put_page(link, FIRST_PAGE.format(name=name())))
    print("Saved the link to %s. Next, if no loop \"Live Notes meeting\" is listed, %s." % (LINK, LOOP))
    print("Then end your turn: the hook hands you meeting lines.")


def publish(path):
    link = read(LINK)
    if not link:
        raise Fail("not in a meeting: run join first")
    text = read(path)
    if not text:
        raise Fail("empty or missing file: %s" % path)
    print(put_page(link, text + "\n"))


def chat(text):
    link = read(LINK)
    if not link:
        raise Fail("not in a meeting: run join first")
    code, d, _ = call("POST", link, "chat", {"text": text})
    if code != 200:
        raise Fail("chat failed (%d): %s" % (code, d.get("error")))
    print("Said in the meeting: %s" % text)


def leave():
    link = read(LINK)
    if link:
        try:
            call("POST", link, "leave", {})
            print("Left the meeting as %s." % name())
        except Fail as e:
            print("Meeting already gone: %s." % e)
    gone = [p for p in [LINK, STATE] + OLD if os.path.exists(p)]
    for p in gone:
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    print("Deleted: %s." % (", ".join(gone) or "nothing, no files were there"))
    print("Now cancel the loop: cron action \"list\", then \"cancel\" the loop named \"Live Notes meeting\".")


def main(argv):
    cmds = {"join": (join, 1), "publish": (publish, 1), "chat": (chat, None), "leave": (leave, 0)}
    if not argv or argv[0] not in cmds:
        print(__doc__.strip())
        return 2
    fn, n = cmds[argv[0]]
    args = argv[1:] if n is not None else [" ".join(argv[1:])]
    if n is not None and len(args) != n or n is None and not args[0]:
        print(__doc__.strip())
        return 2
    try:
        fn(*args)
    except Fail as e:
        print("live_notes: %s" % e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
