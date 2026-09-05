"""Client for the models served via Nebius Token Factory.

## Two models, because one of them cannot see

`settings.nemotron_model_id` classifies every spoken turn;
`settings.vision_model_id` handles the two calls that send an image
(`describe_image`, `diagnose_screen_code`) plus the unused `verify_screen`.

That split is forced, not a preference. This project ran on
`nvidia/Nemotron-3-Nano-Omni`, which handled both, until Nebius removed it
from Serverless on 2026-08-31. Its recommended replacement,
`nvidia/Nemotron-3_5-Lightning`, answers "This model does not support image
input" to every image request - as does every other Nemotron currently on
the endpoint. Checked live rather than assumed: `google/gemma-3-27b-it` and
`openbmb/MiniCPM-V-4_5` are the vision-capable options there, and on the
project's own "what is wrong with this code" screenshot Gemma found the
real bug (division by zero on an empty list) while MiniCPM hallucinated a
missing brace in Python. Hence Gemma as the default, overridable with
VISION_MODEL_ID.

Both are still reached through the same OpenAI-compatible API and the same
client; only the model id differs per call.

## Historical note on image + JSON mode

An earlier deployment returned a hard 400 for `response_format=
{"type": "json_object"}` together with image content, which is why
`interpret_text`'s own `screenshot_path` parameter exists but is never
used. That limitation does not apply to the current vision model -
re-verified live during the migration: image plus json_object works, and
`diagnose_screen_code` depends on it.

Nebius Token Factory exposes an OpenAI-compatible Chat Completions API, so this
uses the `openai` SDK pointed at Nebius's base URL.

`interpret_text` is the path actually used for every spoken turn — text
only. Its `screenshot_path` parameter still builds a `[text, image_url]`
content list when given one, but nothing currently calls it that way: this
same shape (`response_format={"type": "json_object"}` *and* an image)
returned a hard 400 the last time it was tried on this deployment (see the
docstring on `interpret_text` itself), and re-verifying that on every single
turn is not worth the risk for a capability nothing here uses. `interpret()`
sends the full omni payload (audio clip + screenshot + text) and is kept
here, but nothing calls it either: every audio content-part shape tried
(`input_audio`, `audio_url`, `audio`) was rejected with an identical 422 the
moment the content list contains anything other than `text`/`image_url` —
there is no audio-input support on this endpoint. Spoken instructions are
transcribed locally instead (see `heypeer/wakeword/stt.py`) and sent through
`interpret_text`, keeping the actual reasoning/intent step on Nemotron while
working around the missing audio input.

Plain `[text, image_url]` content *without* `json_object` mode, on its own,
separate request, does work — re-confirmed live, repeatedly, right before
adding it: `describe_image` uses exactly that shape for "read_screen", the
one place in this project that actually sends an image today. It is a
second, narrower call for the same reason `summarize_for_speech` is: made
only when a screenshot is genuinely needed, not threaded through the
classifier prompt every turn.
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

Reply in the language the user's turn was actually spoken in - French or
English, whichever it was. This is true for every action below, not only
"reply": the same rule covers what you say while moving a file, opening an
app, or asking a question, not just ordinary conversation. Almost every
example phrase in this prompt happens to be French because the user usually
speaks French - that is a fact about the user, not an instruction to answer
in French regardless of what they actually said. "delete facture.pdf" gets
"Deleting facture.pdf.", not "Suppression du fichier facture.pdf." - the
file name is the only thing that never translates. If the turn is in some
other language entirely, answer in French, the safe default.

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

- Answer in the language the user spoke - French or English, matching them
  turn by turn, not fixed to whichever one they used last. This applies to
  every action's "speech"/"question", not only "reply".
- One or two short sentences. This is spoken aloud; nobody wants a paragraph.
- Sound like a person, not a form. "Tres bien, et toi ?" is a good answer to
  "comment ca va ?". Do not read the file listing back, do not thank the user
  for their question, do not describe your own JSON, and do not repeat the
  user's own words back at them - answer them.
- In French, always "tu", never "vous" - a friend, not a form letter. This
  still applies when reading back something remembered about them (see
  "Things you remember about the user" below): "tu preferes qu'on t'appelle
  Tom", never "vous preferez". A stored fact can read like a neutral,
  third-person note; say it back the same way you would say anything else.
- Never invent a result. If you did not do something, do not say you did.

## ACTIONS

Respond with ONLY a JSON object of one of these forms.

- Say something back and touch nothing on the computer. This covers every
  conversational turn, and anything you are asked to do that is not in the
  list below:
  {"action": "reply", "speech": "<what to say out loud>", \
"end_turn": <true or false>}

- Move ONE named file into a folder (e.g. "deplace le fichier facture vers \
Archives", or "move facture.pdf to Archives"):
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
permanent delete (e.g. "supprime le fichier notes.txt", or "delete \
notes.txt"):
  {"action": "delete_file", \
"src_filename": "<the exact filename from the watched-folder listing>", \
"speech": "<one short sentence>", "end_turn": true}

- Undo the last file action (e.g. "annule", "reviens en arriere"):
  {"action": "undo", "speech": "<one short sentence>", "end_turn": true}

- Start an application (e.g. "lance Spotify", "ouvre Chrome"). Only for a
  real desktop application by its ordinary name, not a path or an
  executable, and not a website or an online service - "ouvre YouTube",
  "va sur Amazon" are not this, see "general_task" below for why:
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

- Look something up on the internet (e.g. "cherche la meteo de demain",
  "recherche des recettes de tarte sur internet", "google la capitale du
  Perou"):
  {"action": "search_web", "query": "<what to search for>", \
"speech": "<one short sentence>", "end_turn": true}
  Use this both when the user asks to look something up, and when they ask
  you a factual question whose answer you do not have - see "Never invent a
  fact" below. If you do know the answer, give it with "reply" instead: do
  not send someone to a search engine for "comment ca va".
  "speech" must say you are opening a search, not pretend to give the
  answer. This action opens a browser; it does not tell the user anything.
  "Je cherche la meteo a Paris." is right, "Voici la meteo a Paris." is a
  promise the browser has to keep.

- Change the system volume (e.g. "baisse le son", "monte le son", "coupe le
  son", "remets le son"):
  {"action": "adjust_volume", "target_name": "<exactly \"up\", \"down\", or \
\"mute\">", "speech": "<one short sentence>", "end_turn": true}
  "coupe"/"mute"/"remets le son" is always "mute" - it is a toggle, not a
  direction, so the same value un-mutes it again.

- Change the screen brightness (e.g. "baisse la luminosite", "augmente la \
luminosite de l'ecran"):
  {"action": "adjust_brightness", "target_name": "<exactly \"up\" or \
\"down\">", "speech": "<one short sentence>", "end_turn": true}

- Maximize an application's window (e.g. "mets Chrome en plein ecran"):
  {"action": "maximize_window", "target_name": "<the application name>", \
"speech": "<one short sentence>", "end_turn": true}

- Minimize an application's window (e.g. "minimise Chrome", "reduis Chrome"):
  {"action": "minimize_window", "target_name": "<the application name>", \
"speech": "<one short sentence>", "end_turn": true}

- Close an application's window (e.g. "ferme Chrome"). This closes the \
window; it does not force-kill the process:
  {"action": "close_window", "target_name": "<the application name>", \
"speech": "<one short sentence>", "end_turn": true}

- Minimize every window (e.g. "montre le bureau", "minimise tout", \
"degage tout"):
  {"action": "minimize_all", "speech": "<one short sentence>", \
"end_turn": true}

- Copy whatever is currently selected, in whichever application has focus \
(e.g. "copie ca", "copie ce texte", "copie cette selection", "copie ce \
paragraphe"). This is a keypress (Ctrl+C), sent no matter what - always use \
this action for "copie X" where X is not a real, named file. Never ask \
whether something is selected, never refuse for "nothing is selected" or \
"I don't know what to copy" - you cannot see the screen and are not \
expected to; sending the keypress is the entire action, whether or not \
anything happens to be selected is not yours to determine or worry about:
  {"action": "clipboard_copy", "speech": "<one short sentence, e.g. \
\"Copie.\" - never claim to know what was copied, never mention whether \
something was selected>", "end_turn": true}
  Only "copie le fichier X" (naming a real file) is different - that is a
  file copy, which is not something you can do; use "reply" and say so.

- Read or summarize the clipboard's current text content (e.g. "qu'est-ce \
qu'il y a dans mon presse-papier ?", "resume ce que j'ai copie", "lis mon \
presse-papier"):
  {"action": "clipboard_read", "speech": "<one short sentence introducing \
what you are about to read or summarize, e.g. \"Voici ce qu'il y a dans \
le presse-papier :\" - not the content itself, which you do not have yet \
when you write this>", "end_turn": true}
  The actual clipboard text is read and, if the user asked for a summary,
  summarized *after* this - you never see it when producing this JSON, so
  do not invent or guess at its content.

- Summarize an existing document (e.g. "resume facture.pdf", "de quoi \
parle ce document ?"). PDF and plain text files only:
  {"action": "summarize_document", \
"target_name": "<the exact filename from the watched-folder listing>", \
"speech": "<one short sentence introducing the summary, e.g. \"Voici un \
resume de facture.pdf :\" - not the summary itself, which you do not have \
yet when you write this>", "end_turn": true}
  Same reasoning as clipboard_read: the document is read and summarized
  *after* this JSON, so do not invent or guess at what it says.

- Look at the screen and answer a question about it (e.g. "qu'est-ce qu'il \
y a sur mon ecran ?", "y a-t-il un message d'erreur ?", "que dit cette \
fenetre ?"):
  {"action": "read_screen", "speech": "<one short sentence, e.g. \"Je \
regarde l'ecran...\" - never describe what is on screen, you have not \
seen it yet when you write this>", "end_turn": true}
  A screenshot is taken and analysed *after* this JSON - you do not see the
  screen when producing it, so never answer the question itself here, only
  announce that you are about to look.

- Explain what is wrong with a NAMED file, without changing anything (e.g. \
"pourquoi facture.py plante ?", "analyse ce fichier", when a filename is \
in the watched-folder listing, was already named earlier in this exchange, \
or the user says one explicitly, e.g. "le fichier C:\\Projets\\calc.py"):
  {"action": "analyze_code", \
"target_name": "<the filename or path - from the watched-folder listing, \
already named earlier in this exchange, or exactly as the user said it>", \
"speech": "<one short sentence, e.g. \"Je regarde le code...\" - you have \
not seen the code yet when you write this, so never diagnose it here>", \
"end_turn": true}
  The file is read and diagnosed *after* this JSON. This only explains -
  nothing is changed. Use "fix_code" instead if the user wants it corrected.

- Diagnose code with NO filename known at all (e.g. "qu'est-ce qui ne va \
pas dans cette fonction ?", "pourquoi ca plante ?" with nothing else to go \
on - no filename in the watched-folder listing, nothing named earlier in \
this exchange, nothing said explicitly). There is no way to know what code \
this is without looking - use "debug_screen_code" instead of guessing at a \
filename or asking which one:
  {"action": "debug_screen_code", \
"speech": "<one short sentence, e.g. \"Je regarde l'ecran...\" - you have \
not looked yet when you write this, so never diagnose anything here>", \
"end_turn": true}
  A screenshot is taken and diagnosed *after* this JSON, the same as \
"read_screen". If a file name becomes identifiable from the screen, the \
diagnosis will say so and it can be referred to on a later turn.

- Fix code (e.g. "corrige-le", "corrige ce fichier", "repare cette \
fonction", "oui, corrige" after a diagnosis asked whether to). This \
actually changes the file - a real coding agent is dispatched to edit it:
  {"action": "fix_code", \
"target_name": "<the filename or path - from the watched-folder listing, \
already named earlier in this exchange (including one identified from the \
screen by a previous "debug_screen_code" turn), or exactly as the user \
said it - never invent one>", \
"speech": "<one short sentence, e.g. \"Je regarde le code...\" - you do \
not know what the fix will be when you write this, so never describe it \
here>", "end_turn": true}
  Only when the user clearly wants the code changed, not merely explained -
  "corrige-le" after a diagnosis already ran is exactly that; "pourquoi ca
  plante ?" alone is a diagnosis action, not this. If no filename is known
  at all - not from the watched folder, not from earlier in this exchange,
  not said explicitly - use "ask" for it rather than inventing one.

- Remember something for later, beyond this exchange (e.g. "retiens que je \
prefere qu'on m'appelle Tom", "note que le projet Facture-Mars doit etre \
livre vendredi", "souviens-toi que mon dossier de travail est Projets"):
  {"action": "remember_fact", \
"content": "<the fact, written plainly and completely enough to be useful \
read back weeks from now with no other context - not \"vendredi\" alone, \
\"le projet Facture-Mars doit etre livre vendredi\">", \
"speech": "<one short sentence, e.g. \"Je m'en souviendrai.\">", \
"end_turn": true}
  This is different from an ordinary answer: it is still true next week, on
  a fresh launch of the app, in an exchange that has not started yet - not
  just for the rest of this conversation.

- Set a timer or a reminder (e.g. "mets un minuteur de 10 minutes", \
"rappelle-moi dans un quart d'heure", "previens-moi dans 2 minutes pour les \
pates", "reveille-moi dans une heure"):
  {"action": "set_reminder", \
"duration_seconds": <how long from now, in seconds, as a number - you do \
the arithmetic: "10 minutes" is 600, "un quart d'heure" is 900, "une heure \
et demie" is 5400>, \
"content": "<what it is for, if they said - \"les pates\" for \"previens-moi \
dans 2 minutes pour les pates\". Empty string when they just asked for a \
timer with no reason given - never invent one>", \
"speech": "<one short sentence confirming it, e.g. \"C'est note, dans 10 \
minutes.\">", "end_turn": true}
  If they gave no duration at all ("mets un minuteur"), use "ask" for it -
  a timer needs a length, and guessing one is worse than asking.
  A time of day rather than a delay ("reveille-moi a 7h") is not this yet:
  answer with "reply" that you only do delays from now for the moment.

- Cancel a timer that is running (e.g. "annule le minuteur", "arrete le \
minuteur des pates", "laisse tomber le rappel"):
  {"action": "cancel_reminder", \
"content": "<which one, in the user's own words - \"les pates\". Empty \
string for \"annule le minuteur\" with nothing to distinguish it>", \
"speech": "<one short sentence, e.g. \"C'est annule.\">", "end_turn": true}

- Say what is left on a running timer (e.g. "il reste combien de temps ?", \
"c'est quoi mes minuteurs ?", "ou en est le minuteur des pates ?"):
  {"action": "list_reminders", "speech": null, "end_turn": true}
  Leave "speech" null: the time left is read from the running timers after
  this JSON, and any sentence written here would be a guess at a number you
  do not have.

- Create a named routine: one phrase the user wants to stand for several \
things at once (e.g. "quand je dis routine du matin, mets de la musique et \
dis-moi mes rendez-vous", "cree une routine boulot qui ouvre VS Code et \
Slack"):
  {"action": "create_routine", \
"target_name": "<what they want to call it, as they said it - \"routine du \
matin\", \"boulot\">", \
"steps": ["<each thing to do, as a plain spoken instruction, exactly the \
way the user would say it on its own - \"mets de la musique\", \"ouvre VS \
Code\">"], \
"speech": "<one short sentence, e.g. \"C'est enregistre.\">", \
"end_turn": true}
  Write each step so it would work as a standalone instruction to you, not
  as a fragment: "ouvre Spotify", never "et puis Spotify". If they named a
  routine but gave no steps, use "ask".

- Run a routine they already have (e.g. "lance ma routine du matin", \
"routine boulot"). The routines that exist are listed for you as "Routines \
you know" - only ever use this action for a name in that list:
  {"action": "run_routine", \
"target_name": "<which one, matching a name from that list>", \
"speech": null, "end_turn": true}
  Leave "speech" null: each step announces itself as it runs, and a
  sentence here would talk over the first one.

- Say which routines exist (e.g. "c'est quoi mes routines ?", "qu'est-ce \
que tu sais faire en routine ?"):
  {"action": "list_routines", "speech": null, "end_turn": true}

- Listen to what the computer is currently playing and answer about it \
(e.g. "qu'est-ce qu'elle dit dans cette video ?", "resume ce qui se dit \
la", "j'ai rate la derniere phrase, c'etait quoi ?"):
  {"action": "listen_to_screen", \
"question": "<what the user wants to know about it, in their own words>", \
"speech": "<one short sentence, e.g. \"J'ecoute...\">", "end_turn": true}
  This captures the sound the machine is playing, not the microphone - it
  is for a video, a call or a track already running, never for something
  said out loud in the room. You do not have the audio while writing this
  JSON; it is captured and answered afterwards, so never guess at what was
  said here.

- Carry out a general, multi-step task with no action above for it, that a \
capable assistant with broader tools (web research, scheduling, browsing \
and interacting with a website - clicking, filling a form, navigating - or \
controlling the desktop more generally) could still reasonably do. This is \
the action for anything on a website or an online service beyond just \
opening it: "ouvre YouTube et joue la derniere video de Squeezie", "va sur \
Amazon et ajoute des piles AA au panier", "clique sur le premier resultat", \
"remplis ce formulaire avec mon adresse" - none of these are "open_app", \
because they need to actually look at a page and act inside it, which \
opening an application by name does not do. Also for anything else with no \
more specific action: "cherche les meilleurs vols pour Paris le mois \
prochain et fais-moi un resume", "programme un rappel chaque lundi pour \
faire le point". Email and calendar live here too: "lis mes derniers \
mails", "reponds a Marc que je serai en retard", "qu'est-ce que j'ai \
demain", "ajoute un rendez-vous avec Sophie jeudi a 14h" - needing a login \
does not make them refusals. Do not use this for anything an action above already \
covers - moving a file, playing music, opening an app by itself, or a \
plain web search with nothing to click, all have their own, more specific \
action:
  {"action": "general_task", \
"content": "<the task, written out fully enough that someone with no other \
context than this sentence could carry it out>", \
"speech": "<one short sentence, e.g. \"Je m'en occupe, ca peut prendre un \
moment...\">", "end_turn": true}
  The task is carried out and its result reported *after* this JSON - you
  do not have the result when producing it, so never claim one here.

- Ask for the one piece you are missing, when the action itself is clear:
  {"action": "ask", \
"question": "<one short question asking for exactly the missing piece, in \
the language the user is speaking - 'Vers quel dossier ?' in French, \
'Which folder?' in English>", \
"end_turn": false}
  Do not use it to re-ask for something already given earlier in the exchange.

Always include every key shown for the form you choose, plus one more on
every single response regardless of which form: "language", either "fr" or
"en" - whichever language "speech"/"question" is actually written in. This
is what tells the speech synthesiser which voice to use, so it has to match
what you actually wrote, not default to "fr" out of habit. Use null for any
other key you have no value for.

This applies just as much to the short, fire-and-forget actions (volume, \
brightness, window control, clipboard) as to longer ones - do not let \
writing a one-line "speech" feel like it does not need "language" set \
correctly too. For "Hey Peer, turn up the volume": \
{"action": "adjust_volume", "target_name": "up", \
"speech": "Turning the volume up.", "language": "en", "end_turn": true} - \
not "language": "fr", even though "monte le son" is the example verb shown \
above, and even though most of this prompt's examples are in French.

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
- search the web: cherche, recherche, google, "trouve-moi", "regarde sur
  internet", "c'est quoi" when they clearly want a web page

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

This action list will grow. When the user asks for something with no action
above for it - editing prose or data inside a document (code is different -
see "fix_code" above), or anything you have no way to reach at all - do NOT
bend it into the nearest action you do have and do NOT invent an action
name. Use "reply", say plainly and briefly that you cannot do that yet, and
set "end_turn" as the conversation warrants. Guessing at an action the user
did not ask for is the worst thing you can do here: it touches something
real.

Email and calendar are NOT in that category, despite needing a login:
"general_task" reaches them. "lis mes derniers mails", "reponds a Marc que
je serai en retard", "qu'est-ce que j'ai comme rendez-vous demain",
"ajoute un point avec Sophie jeudi a 14h" are all "general_task" - never a
refusal, and never "reply" claiming you cannot. What you must not do is
answer them from nothing: you have not read the inbox or the calendar while
writing this JSON, so any specific appointment, sender or subject in
"speech" here would be invented. Say you are going to look, not what you
found.

Never invent a fact. You do not know the current time, and you have not
read the calendar or the inbox at the moment you write this JSON - a
"general_task" can go and look, but its result arrives afterwards, not
here. You do not know what is in a folder you were not shown either. Making one up is worse than saying so: "Il est 14h"
invented on the spot is indistinguishable, to the user, from a real answer.

But not knowing something is not the end of the exchange. Ask yourself, in
this order:

1. Do I already know this? Then "reply", answered. Ordinary knowledge is not
   a reason to open a browser: "combien font deux et deux" and "c'est quoi
   la capitale du Perou" are answers, not searches.
2. Is it about what is currently on the screen - an error message, what a
   window says, whether something specific is visible? Then "read_screen".
   You do not see the screen while writing this JSON, only after - do not
   answer the question here, and do not decline it either, the same way
   "clipboard_read" does not answer from its own JSON.
3. Is it about this computer or this moment specifically, other than the
   screen - the current time, what is in a folder you were not shown? Then
   "reply", saying plainly that you cannot check it.
4. Otherwise a web page has it: "search_web". The weather, the news, opening
   hours, a price, a score, anything that changed after you were trained,
   anything about a specific place or day. Do not refuse it. "Quelle est la
   meteo a Paris aujourd'hui ?" is a search, not something to say no to.

## Output format

Write every string you return using plain ASCII punctuation only: ordinary
hyphens, apostrophes and quotes. No em dashes, non-breaking hyphens or smart
quotes. Accented letters are fine and expected in French - it is only the
typographic punctuation a Windows console cannot encode. These strings are
printed to a terminal and spoken aloud.
"""

# A second, narrower prompt for "clipboard_read" and "summarize_document" -
# once the actual text is available (never seen by the classifier prompt
# above, which only produces intent JSON before anything has been read),
# this turns it into something worth saying out loud rather than reading it
# verbatim - see `NemotronClient.summarize_for_speech`.
ANSWER_ABOUT_TEXT_SYSTEM_PROMPT = """\
You are answering a spoken question about something the user was listening
to. The text you are given is a transcript of audio their computer was
playing - a video, a call, a track - transcribed automatically, so it may
be imperfect, may start mid-sentence, and may end mid-sentence.

Answer their question from that transcript and nothing else. If it does not
contain the answer, say so plainly rather than filling the gap: "ils n'en
parlent pas dans ce que j'ai entendu" is a good answer, an invented one is
not. If the question is general ("qu'est-ce qu'ils disent ?"), summarize
what was said instead.

Two or three short sentences, in the given language, plain ASCII
punctuation. This is read aloud: no bullet points, no headings, no
"according to the transcript".

Respond with ONLY a JSON object: {"answer": "<what to say out loud>"}.
"""


SUMMARIZE_SYSTEM_PROMPT = """\
You turn a block of text into something worth saying out loud. The text
came from the clipboard or a document Hey Peer read for the user; you were
not told which, or anything else about where it came from.

Write two or three short sentences, in the given language, that either
summarize the text (if it is long enough that reading it verbatim would be
tedious) or read it back plainly (if it is already short - a phone number, a
short note, a single sentence). Do not add commentary, do not describe the
text ("this appears to be..."), do not mention the clipboard - the caller
already introduces it out loud before you are asked. Just say what it says.

If the text is not really speakable (a wall of code, a URL, garbage) say so
briefly instead of reading nonsense aloud.

Plain ASCII punctuation only - ordinary hyphens, apostrophes and quotes, no
em dashes or smart quotes; accented letters are fine and expected in French.
Respond with ONLY a JSON object: {"summary": "<what to say>"}.
"""

# A third narrow prompt, for "analyze_code" - diagnosis only, no file
# access, no agent loop. Deliberately not the same call that fixes code
# ("fix_code" dispatches a real coding agent instead, see
# executor/coding_agent.py's module docstring for why): a single completion
# from a small model asked to explain a bug is a reasonable, cheap thing to
# ask for; asked to *also* rewrite the function correctly in the same
# breath, it is exactly the shape of task a real edit/run/verify loop
# exists for and one completion does not replace.
DIAGNOSE_CODE_SYSTEM_PROMPT = """\
You are looking at a piece of code the user asked about. In two to four
short spoken sentences, in the given language, explain what is wrong with
it and why - plainly and concretely, the way you would explain it to
someone standing next to you, not a code review with bullet points.

If the user asked a specific question ("pourquoi ca plante avec les listes
vides ?"), answer that question specifically rather than a generic
walkthrough of the whole function. If the code actually looks fine, say so -
do not invent a problem to sound useful, the same rule as never inventing
any other fact.

Plain ASCII punctuation only. Respond with ONLY a JSON object:
{"diagnosis": "<what to say>"}.
"""

# A fourth prompt, for "debug_screen_code" - the same diagnosis as
# DIAGNOSE_CODE_SYSTEM_PROMPT, but from a screenshot rather than a named
# file's text, for exactly the gap that prompted it: "analyze_code"/
# "fix_code" only ever work on a file already in the watched folder
# (~/Downloads by default) - useless for an actual coding project, which
# lives nowhere near there. Looking at whatever is on screen (almost always
# an editor with the file the user is actually asking about open) sidesteps
# needing a filename at all - the same reasoning "read_screen" already
# established for "what's on my screen", applied to code specifically.
DIAGNOSE_SCREEN_CODE_SYSTEM_PROMPT = """\
You are looking at a screenshot, most likely a code editor, that the user
has a question about. In two to four short spoken sentences, in the given
language:

1. Explain what looks wrong with the code you can see and why - plainly,
   the way you would explain it to someone standing next to you.
2. If you can identify which file this is - a tab name, a window title bar
   (editors usually show "filename - project - Editor Name" there), a path
   visible in a terminal or breadcrumb - say the file name or path plainly
   in your answer, so it can be referred to later. If you cannot tell,
   say so rather than guessing one.
3. Ask whether you should fix it - this is a question, not an action; you
   are not fixing anything by answering this.

If the code actually looks fine, say so plainly and do not invent a problem
or offer to fix something that is not broken.

Name the actual defect and its consequence - "la division echoue si la
liste est vide" - never a restatement that says the same expression twice
("tu utilises X au lieu de X"), and never a vague "il y a une erreur ici".
If you genuinely cannot read the code clearly enough in the screenshot to
tell, say that instead: it is a useful answer, and a confident wrong one is
not.

In French, address the user as "tu", never "vous".

Plain ASCII punctuation only. Respond with ONLY a JSON object:
{"diagnosis": "<what to say>"}.
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


def _string_list(value) -> "list[str] | None":
    """A list of step sentences from the model, or None. Non-strings and
    blanks are dropped rather than rejecting the whole routine: one odd
    element should not lose the four good ones next to it."""
    if not isinstance(value, list):
        return None
    steps = [v.strip() for v in value if isinstance(v, str) and v.strip()]
    return steps or None


def _positive_number(value) -> "float | None":
    """A duration from the model, or None if it isn't one.

    Strict about zero and negatives as well as about types: a timer for
    "0 seconds" or "-5" is a misunderstanding, and scheduling it would fire
    instantly and look like a bug rather than surfacing the problem. The
    caller treats None as "no duration given" and asks."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value > 0 else None


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
        content=data.get("content"),
        # Free text headed for a terminal and a speech synthesiser, unlike
        # the filenames above which must stay byte-exact to match real files.
        question=_plain_punctuation(data.get("question")),
        speech=_plain_punctuation(data.get("speech")),
        language=data.get("language") if data.get("language") in ("fr", "en") else None,
        duration_seconds=_positive_number(data.get("duration_seconds")),
        steps=_string_list(data.get("steps")),
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
        memory: "list[str] | None" = None,
        routines: "list[str] | None" = None,
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
        and the history should be dropped - see `HeyPeer._close_exchange`.

        `memory` is different from `history`: facts told explicitly
        ("retiens que...") that outlive the exchange they were told in - see
        `heypeer/memory.py`'s module docstring for why this is a separate,
        persistent store rather than folded into history. Included on every
        turn, not just when asked about directly, so Nemotron can naturally
        refer to one in an ordinary answer."""
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
        if memory:
            text += f"\nThings you remember about the user from earlier: {json.dumps(memory)}"
        if routines:
            # Names only, never the steps - see executor/routines.py for why
            # that limit is the point rather than an optimisation.
            text += f"\nRoutines you know: {json.dumps(routines)}"

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

    # Kept small: this is read aloud, not analysed, and a long clipboard
    # capture (someone copied an entire document) would otherwise cost a
    # slow, expensive round trip to produce three spoken sentences.
    SUMMARIZE_MAX_CHARS = 4000

    def summarize_for_speech(self, text: str, language: str = "fr") -> str:
        """Turns `text` (clipboard content - see `clipboard_read` in
        `main.py`) into two or three sentences worth saying out loud, in
        `language`.

        A separate, narrower call from `interpret_text` on purpose: the
        classifier prompt produces `clipboard_read`'s JSON *before* the
        clipboard has actually been read (nothing hands it that content),
        so summarizing has to happen afterwards, once there is real text to
        work with - the same reason Spotify's track search is its own call
        rather than something folded into the classifier prompt.
        """
        truncated = text[: self.SUMMARIZE_MAX_CHARS]
        content = f"Language: {'English' if language == 'en' else 'French'}\n\nText:\n{truncated}"
        response = self._client.chat.completions.create(
            model=self.settings.nemotron_model_id,
            messages=[
                {"role": "system", "content": SUMMARIZE_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        if not raw:
            return ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return ""
        return _plain_punctuation(data.get("summary")) or ""

    def answer_about_text(self, text: str, question: str, language: str = "fr") -> str:
        """Answers `question` about `text` - a transcript of what the
        machine was playing (see `executor/system_audio.py`).

        Distinct from `summarize_for_speech` because the user usually asked
        something specific ("j'ai rate la derniere phrase, c'etait quoi ?"),
        and a summary is the wrong answer to a question. The prompt handles
        the general case by falling back to a summary, so this covers both
        without a second call deciding which one to make.
        """
        truncated = text[: self.SUMMARIZE_MAX_CHARS]
        content = (
            f"Language: {'English' if language == 'en' else 'French'}\n"
            f"Question: {question}\n\nTranscript:\n{truncated}"
        )
        response = self._client.chat.completions.create(
            model=self.settings.nemotron_model_id,
            messages=[
                {"role": "system", "content": ANSWER_ABOUT_TEXT_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        if not raw:
            return ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return ""
        return _plain_punctuation(data.get("answer")) or ""

    def diagnose_code(self, code: str, question: str, language: str = "fr") -> str:
        """A short, spoken diagnosis of `code` - what's wrong and why, or
        that it looks fine. `question` is the user's own instruction text,
        so a specific question ("pourquoi ca plante sur une liste vide ?")
        gets answered specifically rather than a generic walkthrough - see
        `DIAGNOSE_CODE_SYSTEM_PROMPT`.

        Diagnosis only: this never edits anything, and is not the call
        `fix_code` uses - see `executor/coding_agent.py`'s module docstring
        for why fixing code is dispatched to a real agent instead of asked
        for in one more completion here.
        """
        truncated = code[: self.SUMMARIZE_MAX_CHARS]
        content = (
            f"Language: {'English' if language == 'en' else 'French'}\n"
            f"Question: {question}\n\nCode:\n{truncated}"
        )
        response = self._client.chat.completions.create(
            model=self.settings.nemotron_model_id,
            messages=[
                {"role": "system", "content": DIAGNOSE_CODE_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        if not raw:
            return ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return ""
        return _plain_punctuation(data.get("diagnosis")) or ""

    def describe_image(self, image_bytes: bytes, question: str, language: str = "fr") -> str:
        """Answers `question` about `image_bytes` (a PNG screenshot) - the
        one place in this project that actually sends an image to Nemotron
        today; see the module docstring for the history behind that being
        worth calling out.

        A short, spoken answer to whatever the user actually asked ("qu'est-
        ce qu'il y a sur mon ecran ?", "y a-t-il un message d'erreur ?"), not
        a generic description - `question` is the user's own instruction
        text, passed straight through, so a specific question gets a
        specific answer rather than a description of the whole screen.
        """
        image_b64 = base64.b64encode(image_bytes).decode()
        content = [
            {
                "type": "text",
                "text": (
                    f"Question ({'English' if language == 'en' else 'French'}): {question}\n\n"
                    'Answer in two or three short spoken sentences, in that language, plain ASCII '
                    'punctuation only. In French address the user as "tu", never "vous". '
                    'Respond with ONLY a JSON object: {"answer": "<the answer>"}'
                ),
            },
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
        ]
        response = self._client.chat.completions.create(
            model=self.settings.vision_model_id,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": content}],
        )
        raw = response.choices[0].message.content
        if not raw:
            return ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return ""
        return _plain_punctuation(data.get("answer")) or ""

    def diagnose_screen_code(self, image_bytes: bytes, question: str, language: str = "fr") -> str:
        """Diagnoses code visible in `image_bytes` (almost always an editor
        screenshot) without needing a filename at all - see
        `DIAGNOSE_SCREEN_CODE_SYSTEM_PROMPT` for why this exists and what it
        asks for: a diagnosis, the file if it can be identified from what is
        on screen, and a question asking whether to fix it - never the fix
        itself, which stays a separate, explicit "fix_code" turn.
        """
        image_b64 = base64.b64encode(image_bytes).decode()
        content = [
            {
                "type": "text",
                "text": (
                    f"Language: {'English' if language == 'en' else 'French'}\nQuestion: {question}"
                ),
            },
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
        ]
        response = self._client.chat.completions.create(
            model=self.settings.vision_model_id,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": DIAGNOSE_SCREEN_CODE_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
        )
        raw = response.choices[0].message.content
        if not raw:
            return ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return ""
        return _plain_punctuation(data.get("diagnosis")) or ""

    def verify_screen(self, screenshot_png: bytes, expected_context: str) -> bool:
        """Visual verification hook used by SkillRunner between replay steps."""
        image_b64 = base64.b64encode(screenshot_png).decode()
        response = self._client.chat.completions.create(
            model=self.settings.vision_model_id,
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
