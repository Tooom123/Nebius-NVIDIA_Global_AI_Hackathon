# Hey Peer — contexte projet

## 1. Contexte du hackathon

Projet soumis au **Nebius x NVIDIA Global AI Hackathon**.

**Contraintes obligatoires du sponsor :**
- Le projet doit tourner sur **Nebius Token Factory** ou **Nebius AI Cloud**.
- Il doit utiliser au moins **un modèle open source NVIDIA** (ici : **Nemotron 3 Nano Omni**, hébergé via Nebius Token Factory).
- Track choisi : **Personal AI** — "assistant toujours actif, privé, avec mémoire persistante, compétences réutilisables, et la capacité d'exécuter des tâches dans le quotidien de l'utilisateur."

**Livrables attendus pour la soumission :**
- Projet fonctionnel
- Description du projet (quoi, pourquoi, comment)
- Démo hébergée (URL) ou test build
- Vidéo démo YouTube publique, ≤ 3 minutes, avec audio expliquant l'usage de Nebius Token Factory et de Nemotron
- Dépôt de code public (GitHub/GitLab/Bitbucket) avec licence open source visible en haut du repo (MIT, Apache 2.0, MPL 2.0...)
- README avec instructions d'installation claires
- Feedback sur les outils Nebius/NVIDIA utilisés

**Critères de jugement à garder en tête pendant le dev :**
- Implémentation technique (usage réel et pertinent de Nebius/Nemotron)
- Design (expérience produit complète, pas juste un POC)
- Impact potentiel (cas d'usage réel et crédible)
- Qualité/originalité de l'idée

## 2. Concept du produit

**Hey Peer** est un assistant personnel qui observe les habitudes numériques de l'utilisateur (séquences répétées d'actions entre applications), détecte les motifs répétitifs, et propose de les automatiser à la demande — activé par la voix via le mot-clé **"Hey Peer"**.

Exemple de scénario cible pour la démo : l'utilisateur répète une tâche (ex. remplir/soumettre un formulaire, trier/renommer des fichiers) 2-3 fois. Il dit ensuite *"Hey Peer, fais-en 4 de plus"*. L'agent identifie le motif appris, demande confirmation, puis l'exécute lui-même via contrôle souris/clavier.

**Ce qu'on NE fait PAS** (pour garder le scope gérable en solo) :
- Pas de surveillance exhaustive de toutes les apps en continu — on capture uniquement ce qu'il faut pour détecter UN motif démontrable dans le scénario de démo.
- Pas d'automatisation "aveugle" — chaque exécution passe par une étape de confirmation explicite avant d'agir.

## 3. Architecture

```
[Capture continue]  →  [Détection de motif + Mémoire des skills]
        │                              │
        │ (mot d'activation "Hey Peer")│
        ▼                              │
[Interprétation — Nemotron 3 Nano Omni]◄──── (consulte la mémoire)
   (Nebius Token Factory · audio + écran)
        │
        ▼
[Confirmation utilisateur]
        │
        ▼
[Exécution — contrôle souris/clavier]
        │
        └──► met à jour la mémoire des skills
```

**Composants :**

1. **Capture continue** — écoute locale et légère : événements clavier/souris abstraits (pas de keylogging du contenu tapé), fenêtre/app active, + détecteur de mot d'activation qui tourne en local (rien n'est envoyé au cloud tant que "Hey Peer" n'est pas détecté — argument privacy fort pour le pitch).

2. **Wake word "Hey Peer"** — modèle **openWakeWord** entraîné sur mesure :
   - Génération de samples synthétiques via **Piper TTS** (dizaines/centaines de prononciations de "Hey Peer", voix/vitesses/tons variés)
   - Augmentation (bruit de fond, réverbération de pièce)
   - Extraction en spectrogramme mel + entraînement d'un petit CNN/DNN
   - Sortie : modèle ONNX léger (~200 Ko), tourne en temps réel sur CPU, faible latence
   - Pipeline recommandé : `piper-sample-generator` + script d'entraînement openWakeWord, exécutable sur Colab (GPU) en quelques heures

3. **Détection de motif + mémoire des skills** — logique qui repère une séquence répétée (ex. 3 occurrences de la même suite d'actions), la stocke comme "skill" paramétrable (JSON ou petite base locale suffisant pour la démo). C'est ce que Nemotron consulte pour comprendre une commande comme "encore 4".

4. **Interprétation (Nemotron 3 Nano Omni via Nebius Token Factory)** — reçoit le clip audio post-activation + une capture d'écran de l'état courant, raisonne sur les deux (modèle omni-modal : audio + vision + texte), et retourne une intention structurée : `{action, skill_id, n_repetitions, ...}`.

5. **Confirmation utilisateur** — avant toute action, affichage clair de ce qui va être fait ("je vais faire X, N fois") et attente de validation. Non négociable : sécurité + argument de design pour le jury.

6. **Exécution automatisée** — replay des actions via `pyautogui` (Python) ou `robotjs` (Node), avec une vérification visuelle légère entre chaque étape (rappel à Nemotron pour confirmer que l'écran correspond à l'état attendu) afin d'éviter les dérapages si l'interface a changé.

## 4. Stack technique (proposition de départ)

- **Langage principal** : Python (cohérent avec openWakeWord, pyautogui, et les SDK d'inférence)
- **Wake word** : openWakeWord (ONNX runtime), entraîné via Piper TTS
- **Inférence LLM/vision** : appels API vers **Nebius Token Factory**, modèle **Nemotron 3 Nano Omni**
- **Automatisation UI** : `pyautogui` (+ éventuellement `pillow`/`opencv` pour la vérification visuelle d'étape)
- **Mémoire des skills** : stockage local simple (JSON ou SQLite) — pas besoin de plus pour la démo
- **Interface de confirmation** : UI minimaliste (CLI, overlay léger, ou petite fenêtre) — à trancher selon le temps disponible

## 5. Plan d'attaque

1. Entraîner le wake word "Hey Peer" (Piper TTS → augmentation → entraînement openWakeWord → export ONNX)
2. Mettre en place une capture d'activité minimale viable, ciblée sur UN scénario démontrable
3. Implémenter la détection de motif + mémoire des skills
4. Câbler l'appel à Nemotron 3 Nano Omni via Nebius Token Factory (tester d'abord avec des exemples texte avant de brancher l'audio réel)
5. Construire l'écran de confirmation
6. Implémenter l'exécution automatisée avec vérification visuelle
7. Préparer la démo (scénario unique, répétable), le README, la licence open source, et la vidéo de 3 minutes

## 6. Points d'attention / décisions encore ouvertes

- Choisir précisément le scénario de démo unique (ex. tri de fichiers, remplissage de formulaire répétitif) — doit être simple à répéter et convaincant en vidéo courte.
- Décider du format de l'écran de confirmation (CLI suffisant pour un MVP hackathon, ou petite UI).
- Vérifier les quotas/limites d'API sur Nebius Token Factory pour Nemotron 3 Nano Omni avant de builder la démo finale.
- Prévoir dans le README une note explicite sur les considérations éthiques (contrôle utilisateur, confirmation obligatoire, mot d'activation local pour la confidentialité).