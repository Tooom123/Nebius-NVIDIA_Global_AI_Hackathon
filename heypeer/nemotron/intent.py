"""Structured intent returned by Nemotron after interpreting a voice command."""

from dataclasses import dataclass


ACTIONS = (
    "move_file",
    "rename_file",
    "create_file",
    "create_folder",
    "delete_file",
    "undo",  # revert the last file action ("annule")
    "open_app",  # start an application by name ("lance Spotify")
    "play_music",  # play something specific ("mets Alright de Kendrick Lamar")
    "search_web",  # look something up in a browser ("cherche X sur internet")
    "adjust_volume",  # "monte/baisse/coupe le son" - target_name is up/down/mute
    "adjust_brightness",  # "monte/baisse la luminosite" - target_name is up/down
    "maximize_window",  # "mets X en plein ecran" - target_name is the app
    "minimize_window",  # "minimise X" - target_name is the app
    "close_window",  # "ferme X" - target_name is the app
    "minimize_all",  # "montre le bureau", "minimise tout" - no target
    "clipboard_copy",  # "copie ca" - simulates Ctrl+C, no target
    "clipboard_read",  # "qu'est-ce qu'il y a dans mon presse-papier ?" - no target
    "summarize_document",  # "resume ce pdf" - target_name is the filename
    "read_screen",  # "qu'est-ce qu'il y a sur mon ecran ?" - no target
    "analyze_code",  # "pourquoi cette fonction plante ?" - target_name is the filename
    "fix_code",  # "corrige-le", "corrige ce fichier" - target_name is the filename
    "debug_screen_code",  # "qu'est-ce qui ne va pas ici ?" with no filename - looks at the screen
    "remember_fact",  # "retiens que..." - content is the fact
    "general_task",  # a multi-step task outside every action above - content is the task
    "set_reminder",  # "rappelle-moi dans 10 minutes" - content is the label, duration_seconds the delay
    "cancel_reminder",  # "annule le minuteur" - content is which one, empty for all/the only one
    "list_reminders",  # "il me reste combien de temps ?" - no field
    "reply",  # nothing to do on the computer: just say `speech` back
    "ask",  # the instruction was almost understood; `question` says what's missing
    "unknown",
)

# Actions that are a spoken answer rather than something done to the machine.
# Both are handled identically; they are kept apart only because the prompt
# distinguishes them, and the distinction is worth keeping in the logs.
SPOKEN_ACTIONS = ("reply", "ask")

# What each action actually is, in the plain English used to check the
# prompt's own "Things you cannot do yet" section against reality (see
# test_nemotron_client.py's prompt-contradiction guard). Twice now, an
# action shipped in the dispatch code while the prompt still refused it in
# prose written before that action existed (round 29: apps and web search;
# round 31: the same for the weather, i.e. web search again). Both times a
# human had to say the exact sentence live before anyone noticed.
#
# This does not automate the fix - the guard test still greps prompt prose,
# which is free text and can always drift in a way no table catches - but it
# makes the *list of things to check for* follow from ACTIONS mechanically,
# so a new action missing its entry here fails on its own, right where the
# action is declared, rather than the guard test silently checking a
# now-incomplete hand-copied list forever.
ACTION_DESCRIPTIONS = {
    "move_file": "move a file",
    "rename_file": "rename a file",
    "create_file": "create a file",
    "create_folder": "create a folder",
    "delete_file": "delete a file",
    "undo": "undo",
    "open_app": "open an application",
    "play_music": "play music",
    "search_web": "search the web",
    "adjust_volume": "change the volume",
    "adjust_brightness": "change the screen brightness",
    "maximize_window": "maximize a window",
    "minimize_window": "minimize a window",
    "close_window": "close a window",
    "minimize_all": "minimize every window",
    "clipboard_copy": "copy the current selection",
    "clipboard_read": "read the clipboard",
    "summarize_document": "summarize a document",
    "read_screen": "see or read the screen",
    "analyze_code": "explain what is wrong with some code",
    "fix_code": "fix code",
    "debug_screen_code": "diagnose code by looking at the screen",
    "remember_fact": "remember something for later",
    "general_task": "carry out a general, multi-step task",
    "set_reminder": "set a timer or a reminder",
    "cancel_reminder": "cancel a timer",
    "list_reminders": "say how long is left on a timer",
}


@dataclass(frozen=True)
class Intent:
    action: str  # one of ACTIONS
    skill_id: str | None
    n_repetitions: int
    # "move_file"/"rename_file"/"delete_file": an exact filename from the
    # directory listing given as context.
    src_filename: str | None = None
    # "move_file" only: destination folder name (created under the watched
    # directory if it doesn't exist yet).
    dest_folder: str | None = None
    # "rename_file" only: the file's new name (same folder).
    new_name: str | None = None
    # "create_file"/"create_folder"/"open_app" (the application name)/
    # "maximize_window"/"minimize_window"/"close_window" (the application
    # whose window it is)/"summarize_document"/"analyze_code"/"fix_code"
    # (an existing file's name): the name in question. "adjust_volume" and
    # "adjust_brightness" reuse it too, for their direction - "up", "down",
    # or (volume only) "mute" - since these actions have no other target of
    # their own.
    target_name: str | None = None
    # "play_music" and "search_web": what to look for, as one search string.
    # For music, "X par Y" is flattened to "X Y" - the preposition is French
    # grammar, not part of the title, and a music search expects neither.
    query: str | None = None
    # "remember_fact" (the fact itself) / "general_task" (the task, verbatim
    # enough for another agent to act on without the rest of this exchange).
    # A separate field from "query" on purpose - a search string and a fact
    # to remember or a task to hand off are not the same shape of text, and
    # conflating them would blur what each action actually does with it.
    content: str | None = None
    # "ask" only: the single short question to put to the user, in whichever
    # language they are speaking (see `language` below). Lets Hey Peer say
    # what's actually missing ("vers quel dossier ?") instead of a flat
    # "je n'ai pas compris" that leaves them guessing.
    question: str | None = None
    # What to say out loud. Required for "reply", where it *is* the whole
    # response; optional on a file action, where it replaces the fixed
    # narration with something phrased for the actual request.
    speech: str | None = None
    # The language "speech"/"question" is actually written in - "fr" or
    # "en", the two Piper voices Hey Peer has. Nemotron reports this itself
    # rather than the caller guessing it from the text afterwards: a
    # language guess on a short spoken sentence is unreliable (langdetect-
    # style heuristics are notoriously bad on a handful of words), where
    # Nemotron already knows which language it just wrote in because it
    # chose to write in it. None (a malformed or pre-language-aware answer)
    # falls back to French - see tts.speak.
    language: str | None = None
    # "set_reminder" only: how far ahead to fire, in seconds. Nemotron does
    # the unit arithmetic ("dans un quart d'heure" -> 900): it already
    # understands the phrasing, and a second parser here would be one more
    # place for "une heure et demie" to be got wrong.
    duration_seconds: float | None = None
    # Whether the exchange is finished. False keeps the microphone open for a
    # reply with no wake word, which is what makes this a conversation rather
    # than a series of unrelated commands: Hey Peer stops listening when the
    # discussion is over or the task is done, not after every single turn.
    #
    # Defaults to True so anything that does not think about it - an older
    # answer, a parse failure - closes the exchange rather than leaving the
    # microphone open indefinitely.
    end_turn: bool = True
