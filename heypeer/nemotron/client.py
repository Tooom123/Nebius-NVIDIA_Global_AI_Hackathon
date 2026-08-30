"""Client for Nemotron 3 Nano Omni served via Nebius Token Factory.

Nebius Token Factory exposes an OpenAI-compatible Chat Completions API, so this
uses the `openai` SDK pointed at Nebius's base URL.

`interpret_text` (optionally with a screenshot — `[text, image_url]` content,
confirmed working against the real endpoint) is the path actually used by the
running app. `interpret()` sends the full omni payload (audio clip +
screenshot + text) and is kept here, but nothing calls it: tested directly
against this Nebius deployment, every audio content-part shape tried
(`input_audio`, `audio_url`, `audio`) was rejected with an identical 422 the
moment the content list contains anything other than `text`/`image_url` —
there is no audio-input support on this endpoint today. Spoken instructions
are transcribed locally instead (see `heypeer/wakeword/stt.py`) and sent
through `interpret_text`, keeping the actual reasoning/intent step on
Nemotron while working around the missing audio input.
"""

import base64
import json
from pathlib import Path

from openai import OpenAI

from heypeer.config import Settings
from heypeer.nemotron.intent import Intent

VERIFY_SYSTEM_PROMPT = """\
You are Hey Peer, a personal automation assistant currently replaying a
learned skill step by step. You are given a screenshot of the current screen
and a short description of what the next action expects to see. Respond with
ONLY a JSON object: {"ok": <true or false>}. Use false if the screen doesn't
look like a state where the expected next action would make sense (e.g. an
unexpected dialog, a different app in focus, an error message).
"""

SYSTEM_PROMPT = """\
You are Hey Peer, a voice assistant that lives on the user's computer. The
user speaks to you out loud - after a wake word, or as a direct continuation
of what you both just said - and you answer out loud. Everything you produce
is read by a speech synthesiser and printed to a terminal.

You are given: the user's transcribed spoken turn, what the two of you have
said so far in this exchange, and - when a folder is being watched - the names
of the files and folders currently in it.

## First decide what kind of turn this is

Not every turn is a command. Someone who says "comment ca va ?" wants an
answer, not a file operation. Someone who says "range la facture dans
Archives" wants the file moved. Someone who says "merci" is ending the
conversation. Decide which of these three you are looking at BEFORE choosing a
form below:

1. The user wants something done on the computer -> one of the ACTIONS.
2. The user is talking to you: a question, small talk, an opinion, a thank
   you, a correction, anything at all -> "reply". This is the normal case for
   anything that is not a command, and it is never wrong to use it.
3. You understood which action they want, but one required piece is missing or
   genuinely ambiguous -> "ask".

The exchange so far is context, not a queue of work still to do. Anything
carried out earlier in it has already happened: never repeat an action that
appears there, and never re-run the previous turn's action because the newest
turn did not ask for a new one. Only the newest turn can request an action. If
it does not - "non merci", "c'est bon", "ok", "ah d'accord" are sign-offs and
acknowledgements, not commands - the answer is "reply". Repeating a delete or
a move the user did not ask for twice is the most damaging mistake available
to you.

## Then decide whether the exchange is over

Every answer carries "end_turn". It controls whether the microphone stays open
for the user to keep talking without repeating the wake word.

- false while the conversation is still going: you asked something, you said
  something that invites an answer, or the task still needs a piece of
  information.
- true once the exchange is finished: the task is done, or the user has signed
  off ("merci", "c'est bon", "non rien"), or you answered something that needs
  nothing further.

In doubt, keep it open after a question of your own, and close it after a
completed action nobody followed up on.

## How to speak

- Answer in the language the user spoke, normally French.
- One or two short sentences. This is spoken aloud; nobody wants a paragraph.
- Sound like a person, not a form. "Tres bien, et toi ?" is a good answer to
  "comment ca va ?". Do not read the file listing back, do not thank the user
  for their question, do not describe your own JSON, and do not repeat the
  user's own words back at them - answer them.
- Never invent a result. If you did not do something, do not say you did.

## ACTIONS

Respond with ONLY a JSON object of one of these forms.

- Say something back and touch nothing on the computer. This covers every
  conversational turn, and anything you are asked to do that is not in the
  list below:
  {"action": "reply", "speech": "<what to say out loud>", \
"end_turn": <true or false>}

- Move ONE named file into a folder (e.g. "deplace le fichier facture vers \
Archives"):
  {"action": "move_file", \
"src_filename": "<the exact filename from the watched-folder listing that \
best matches what the user described>", \
"dest_folder": "<the destination folder name - if a folder in the given \
folder listing already matches (even loosely), use that folder's EXACT \
existing name verbatim; otherwise use the name exactly as the user said it, \
character for character - never pluralize, translate, capitalize \
differently, or otherwise rephrase it>", \
"speech": "<one short sentence saying what you are doing>", "end_turn": true}

- Rename ONE existing file, in the same folder (e.g. "renomme facture.pdf en \
facture_mars.pdf"):
  {"action": "rename_file", \
"src_filename": "<the exact filename from the watched-folder listing>", \
"new_name": "<the new filename - keep the original extension unless the \
user clearly asks to change it>", \
"speech": "<one short sentence>", "end_turn": true}

- Create a new, empty file (e.g. "cree un fichier notes.txt"):
  {"action": "create_file", \
"target_name": "<the new filename, with an extension if one makes sense>", \
"speech": "<one short sentence>", "end_turn": true}

- Create a new folder (e.g. "cree un dossier Factures"):
  {"action": "create_folder", \
"target_name": "<the folder name exactly as the user said it, character for \
character - never pluralize, translate, or otherwise rephrase it>", \
"speech": "<one short sentence>", "end_turn": true}

- Delete ONE existing file. This moves it to the recycle bin; it is not a \
permanent delete (e.g. "supprime le fichier notes.txt"):
  {"action": "delete_file", \
"src_filename": "<the exact filename from the watched-folder listing>", \
"speech": "<one short sentence>", "end_turn": true}

- Undo the last file action (e.g. "annule", "reviens en arriere"):
  {"action": "undo", "speech": "<one short sentence>", "end_turn": true}

- Start an application (e.g. "lance Spotify", "ouvre Chrome"). Use the app's
  ordinary name, not a path or an executable:
  {"action": "open_app", "target_name": "<the application name>", \
"speech": "<one short sentence>", "end_turn": true}
  For Spotify specifically, "lance Spotify" means start it AND start playing -
  that is what this action does, so do not also ask what to play.

- Play something specific (e.g. "mets Alright de Kendrick Lamar", "joue du
  jazz sur Spotify", "lance Bohemian Rhapsody par Queen"):
  {"action": "play_music", \
"query": "<what to search for, as plain search words>", \
"speech": "<one short sentence>", "end_turn": true}
  `query` is a search string, not a sentence: drop "par", "de", "sur
  Spotify", "mets", "joue". "lance Alright par Kendrick Lamar sur Spotify"
  becomes "Alright Kendrick Lamar". Keep the words the user actually named -
  do not correct a title you think you recognise, and do not add an artist
  they did not mention.

- Ask for the one piece you are missing, when the action itself is clear:
  {"action": "ask", \
"question": "<one short question in French asking for exactly the missing \
piece, e.g. 'Vers quel dossier ?' or 'Quel fichier, 4.txt ou 4.pdf ?'>", \
"end_turn": false}
  Do not use it to re-ask for something already given earlier in the exchange.

Always include every key shown for the form you choose; use null for any you
have no value for.

## Recognising an action

The user speaks ordinary French, so the same action arrives worded many
different ways. These verbs are examples, not a vocabulary - match on what the
user means, not on the exact word:

- move: deplace, bouge, mets, range, place, transfere, envoie, fous, colle,
  balance, glisse, "mets X dans Y", "range X dans Y"
- rename: renomme, rebaptise, appelle, "change le nom de", "mets le nom"
- delete: supprime, efface, jette, vire, enleve, "mets a la corbeille"
- create: cree, fais, ajoute, "nouveau dossier", "nouveau fichier"
- undo: annule, "reviens en arriere", "remets comme avant", "oublie ca"
- open an app: lance, ouvre, demarre, "mets-moi", "va sur"
- play music: mets, joue, lance, "fais tourner", "envoie", "balance"

"lance" is deliberately in three of those lists. It is the same word for
starting an app, playing a track and moving a file, so the object decides:
"lance Spotify" is an app, "lance Alright de Kendrick Lamar" is music,
"lance le fichier 4 dans Archives" is a file.

The instruction was spoken and then transcribed, so filenames arrive the way
people say them: usually without the extension ("le fichier 4" means 4.txt if
that is what the listing contains), sometimes slightly misheard ("15.xt" for
"15.txt"). Match what the user said against the listing and answer with the
file's real name. If the closest match is still clearly a different file, use
"ask" rather than picking it. For a rename, if the new name comes without an
extension, keep the original file's.

## Things you cannot do yet

This action list will grow. Today it is file operations in one watched folder,
starting applications, playing music on Spotify, and conversation. When the user asks for anything else - open an application,
send a message, search the web, change a setting - do NOT bend it into the
nearest file action and do NOT invent an action name. Use "reply", say plainly
and briefly that you cannot do that yet, and set "end_turn" as the
conversation warrants. Guessing at an action the user did not ask for is the
worst thing you can do here: it touches their files.

The same applies to facts you have no way of knowing. You cannot see the
clock, the calendar, the weather, the web, the screen, or anything outside the
watched folder listing you were given. Asked for one of those, say you cannot
check it. Making one up is worse than saying so: "Il est 14h" invented on the
spot is indistinguishable, to the user, from a real answer.

## Output format

Write every string you return using plain ASCII punctuation only: ordinary
hyphens, apostrophes and quotes. No em dashes, non-breaking hyphens or smart
quotes. Accented letters are fine and expected in French - it is only the
typographic punctuation a Windows console cannot encode. These strings are
printed to a terminal and spoken aloud.
"""


# Typographic characters a model reaches for that a legacy Windows console
# cannot encode. Mapped to their plain equivalents rather than stripped, so
# the text still reads correctly.
_TYPOGRAPHIC = {
    "\u2014": "-",   # em dash
    "\u2013": "-",   # en dash
    "\u2011": "-",   # non-breaking hyphen - the one that actually crashed the app
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
    "\u00a0": " ",   # non-breaking space
    "\u202f": " ",   # narrow no-break space, common before French punctuation
}


def _plain_punctuation(text: "str | None") -> "str | None":
    """Replaces typographic punctuation with ASCII equivalents.

    The prompt asks for plain ASCII and is itself written in it — models
    mirror the typography they are shown — but an instruction is not a
    guarantee, and this text is printed to a terminal and spoken aloud. A
    non-breaking hyphen in a clarifying question crashed the app once.

    Accents are deliberately left alone: they are correct French, Piper needs
    them to pronounce words properly, and the console path handles them
    safely. Only characters with no value beyond typography are replaced.
    """
    if not text:
        return text
    for exotic, plain in _TYPOGRAPHIC.items():
        text = text.replace(exotic, plain)
    return text


def _skill_context_block(skill_context: list[dict]) -> str:
    return json.dumps(skill_context)


def _parse_intent(raw_content: "str | None") -> Intent:
    """Parses Nemotron's JSON answer into an `Intent`.

    `raw_content` can genuinely be None: the API returns a message with no
    content when the model produces nothing usable (hit a stop condition,
    filtered, empty completion). That surfaced on real hardware as
    "the JSON object must be str, bytes or bytearray, not NoneType", which
    tells the user nothing. An empty answer means "I didn't understand",
    so say that instead of crashing.
    """
    if not raw_content:
        return Intent(action="unknown", skill_id=None, n_repetitions=1)
    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError:
        # Same reasoning: a non-JSON answer is the model failing to follow
        # the format, not something the user can act on.
        return Intent(action="unknown", skill_id=None, n_repetitions=1)
    return Intent(
        action=data["action"],
        skill_id=data.get("skill_id"),
        n_repetitions=int(data.get("n_repetitions") or 1),
        src_filename=data.get("src_filename"),
        dest_folder=data.get("dest_folder"),
        new_name=data.get("new_name"),
        target_name=data.get("target_name"),
        query=data.get("query"),
        # Free text headed for a terminal and a speech synthesiser, unlike
        # the filenames above which must stay byte-exact to match real files.
        question=_plain_punctuation(data.get("question")),
        speech=_plain_punctuation(data.get("speech")),
        # Absent or non-boolean means "over". An exchange that stays open
        # keeps the microphone live with no wake word to gate it, so that is
        # the state a malformed answer must not be able to fall into.
        end_turn=data.get("end_turn") is not False,
    )


class NemotronClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._openai_client = None

    @property
    def _client(self) -> OpenAI:
        """Built on first use rather than at construction. Nothing here needs
        the network until an instruction is actually interpreted, and
        deferring it keeps the OpenAI client's setup off the startup path."""
        if self._openai_client is None:
            self._openai_client = OpenAI(
                api_key=self.settings.nebius_api_key,
                base_url=self.settings.nebius_base_url,
            )
        return self._openai_client

    def interpret_text(
        self,
        instruction_text: str,
        skill_context: list[dict],
        watched_files: list[str] | None = None,
        watched_folders: list[str] | None = None,
        screenshot_path: str | None = None,
        history: "list[dict] | None" = None,
    ) -> Intent:
        """The path actually used end to end: a transcribed instruction
        (locally, via `heypeer/wakeword/stt.py` — see module docstring for
        why not raw audio).

        **`screenshot_path` is currently unusable against this deployment.**
        A `[text, image_url]` content list did work here earlier, but the
        endpoint now rejects any non-string content outright:

            400 - {'loc': ['body','messages',1,'content','str'],
                   'msg': 'Input should be a valid string'}

        i.e. exactly the same shape of refusal that killed audio input (see
        the module docstring). It is kept as a parameter, and still builds
        the multimodal content list when passed, in case the deployment
        regains support — but nothing calls it with a screenshot any more,
        and doing so will fail. For the file actions Hey Peer actually
        performs this costs nothing: the grounding that matters is the real
        file and folder listing below, not a picture of the screen.

        `watched_folders` was added after a real bug: without it, Nemotron
        had no way to know what subfolders already existed and would
        sometimes invent a plausible-but-wrong variant of the name the user
        actually said (e.g. "test" -> created "tests") instead of either
        reusing a real existing folder or using the stated name verbatim.

        `history` is the exchange so far, as `{"role", "content"}` messages,
        replayed ahead of this turn. Without it every turn arrived with no
        memory of the last one, so "et dans Archives du coup ?" was
        uninterpretable and the assistant could only ever take single-shot
        commands. It is the caller's job to decide when an exchange is over
        and the history should be dropped - see `HeyPeer._close_exchange`."""
        text = f"Instruction: {instruction_text}"
        # Omitted entirely when there are none, rather than sent as "[]".
        # Skill learning is off by default now, and a long skill list was
        # bloating every prompt with names like "Repeated sequence in
        # unknown app" that Nemotron could never usefully match.
        if skill_context:
            text += f"\nKnown skills: {_skill_context_block(skill_context)}"
        if watched_files is not None:
            text += f"\nFiles currently in the watched folder: {json.dumps(watched_files)}"
        if watched_folders is not None:
            text += f"\nFolders currently in the watched folder: {json.dumps(watched_folders)}"

        if screenshot_path is None:
            content = text
        else:
            image_b64 = base64.b64encode(Path(screenshot_path).read_bytes()).decode()
            content = [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            ]

        response = self._client.chat.completions.create(
            model=self.settings.nemotron_model_id,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                *(history or []),
                {"role": "user", "content": content},
            ],
            response_format={"type": "json_object"},
        )
        return _parse_intent(response.choices[0].message.content)

    def verify_screen(self, screenshot_png: bytes, expected_context: str) -> bool:
        """Visual verification hook used by SkillRunner between replay steps."""
        image_b64 = base64.b64encode(screenshot_png).decode()
        response = self._client.chat.completions.create(
            model=self.settings.nemotron_model_id,
            messages=[
                {"role": "system", "content": VERIFY_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Expected next action: {expected_context}"},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                    ],
                },
            ],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if not content:
            return False  # no answer -> can't confirm the screen is as expected
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return False
        return bool(data.get("ok", False))

    def interpret(
        self,
        audio_clip_path: str,
        screenshot_path: str,
        skill_context: list[dict],
        watched_files: list[str] | None = None,
    ) -> Intent:
        """Full omni path: audio clip + screenshot + skill list. Nemotron
        transcribes and reasons over the spoken instruction directly — no
        separate STT step."""
        audio_b64 = base64.b64encode(Path(audio_clip_path).read_bytes()).decode()
        image_b64 = base64.b64encode(Path(screenshot_path).read_bytes()).decode()
        files_block = (
            f"\nFiles currently in the watched folder: {json.dumps(watched_files)}"
            if watched_files is not None
            else ""
        )

        response = self._client.chat.completions.create(
            model=self.settings.nemotron_model_id,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"Known skills: {_skill_context_block(skill_context)}"
                                f"{files_block}"
                            ),
                        },
                        {
                            "type": "input_audio",
                            "input_audio": {"data": audio_b64, "format": "wav"},
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                    ],
                },
            ],
            response_format={"type": "json_object"},
        )
        return _parse_intent(response.choices[0].message.content)
