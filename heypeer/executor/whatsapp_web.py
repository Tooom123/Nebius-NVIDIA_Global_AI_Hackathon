"""Writing a WhatsApp message in WhatsApp Web, over CDP in the demo's Chrome.

Fixed steps for the same reason as spotify_app.py: the agent did this
part, and in one rehearsal left a message to Tally carrying the link of a
playlist it had just deleted, because the chat box still held the draft
of the run before. Here the box is emptied and checked empty every time.
"""

import json
import time

SEARCH = ("document.querySelector('input[aria-label=\"Search or start a new chat\"], "
          "input[aria-label=\"Rechercher ou démarrer une discussion\"], "
          "#side input[role=\"textbox\"], #side [contenteditable=\"true\"]')")
BOX = "document.querySelector('footer [contenteditable=\"true\"]')"


def _chat_js(contact: str) -> str:
    return ("[...document.querySelectorAll('#pane-side span[title], #side span[title]')]"
            f".filter(e => e.offsetParent).find(e => e.title.toLowerCase().startsWith("
            f"{json.dumps(contact.lower())}))")


def _open_chat(page, contact: str, attempts: int = 3) -> bool:
    """Clicks the contact in the search results until their chat is the
    one open. The list redraws as the results arrive, and a click aimed at
    the row before that landed beside it - measured, nothing opened."""
    header = ("(document.querySelector('#main header') || {innerText: ''}).innerText"
              f".toLowerCase().startsWith({json.dumps(contact.lower())})")
    for _ in range(attempts):
        time.sleep(1.5)
        try:
            page.wait_for(f"!!({_chat_js(contact)})", timeout=10)
            page.click(_chat_js(contact))
            page.wait_for(f"{header} && !!{BOX}", timeout=5)
            return True
        except Exception:
            continue
    return False


def write_message(contact: str, text: str, send: bool, log=print) -> bool:
    """Opens the chat with the first contact whose name starts with
    `contact`, replaces whatever is in the box with `text`, and sends it
    when `send` is set. Returns whether the box holds (or sent) `text`."""
    from heypeer.executor.cdp import Page

    page = Page(_port(), "web.whatsapp.com")
    try:
        page.wait_for(f"!!{SEARCH}", timeout=30)
        page.click(SEARCH)
        page.select_all_and_delete()
        page.type_text(contact)
        if not _open_chat(page, contact):
            log(f"WhatsApp: the chat with {contact} did not open.")
            return False
        page.click(BOX)
        page.select_all_and_delete()
        time.sleep(0.4)
        if page.js(f"{BOX}.innerText.trim()"):
            log("WhatsApp: the chat box would not empty.")
            return False
        page.type_text(text)
        time.sleep(0.4)
        written = page.js(f"{BOX}.innerText.trim()") == text.strip()
        if not written:
            log("WhatsApp: the message in the box is not the one typed.")
            return False
        if send:
            # The link's preview card is fetched after the text goes in;
            # sent at once, the message went without it.
            time.sleep(3)
            page.enter()
            time.sleep(1)
            log(f"WhatsApp: sent to {contact}.")
        else:
            log(f"WhatsApp: message to {contact} written, not sent (dry run).")
        return True
    finally:
        page.close()


def _port() -> int:
    from heypeer.executor import browser

    return browser._port()
