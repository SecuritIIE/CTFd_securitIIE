"""
CTFd Plugin — Instance Launcher
================================
Ajoute sur les challenges tagués "instance" un bouton "Lancer une instance".

Quand l'utilisateur clique :
  1. Ce plugin appelle le launcher local (127.0.0.1:5001)
  2. Le launcher démarre (ou retrouve) le binaire du challenge sur un port libre
  3. Le plugin retourne le port à afficher à l'utilisateur

Configuration (CTFd/config.ini, section [extra]) :
  LAUNCHER_URL  = http://127.0.0.1:5001   # URL du service launcher
  LAUNCHER_TAG  = instance                 # Tag CTFd qui active le launcher
  CTF_HOST      = ctf.mondomaine.fr        # Hostname affiché dans "nc <host> <port>"
"""

import logging
import os

import requests
from flask import Blueprint, jsonify, request

from CTFd.models import Challenges
from CTFd.plugins import (
    bypass_csrf_protection,
    register_plugin_assets_directory,
    register_plugin_script,
)
from CTFd.utils import get_app_config
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_user

log = logging.getLogger(__name__)
PLUGIN_DIR = os.path.dirname(__file__)

# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------
instance_bp = Blueprint(
    "instance_launcher",
    __name__,
    url_prefix="/plugins/instance_launcher",
)

# ---------------------------------------------------------------------------
# Helpers : accès à la config CTFd
# ---------------------------------------------------------------------------

def _launcher_url() -> str:
    return get_app_config("LAUNCHER_URL") or "http://127.0.0.1:5001"

def _launcher_tag() -> str:
    return (get_app_config("LAUNCHER_TAG") or "instance").lower()

def _ctf_host() -> str:
    return get_app_config("CTF_HOST") or "localhost"

# ---------------------------------------------------------------------------
# Fonctions d'appel au service launcher (utilisables hors contexte HTTP)
# ---------------------------------------------------------------------------

def launch_instance_for_user(user_id: int, challenge_id: str) -> dict:
    """Appelle le launcher pour créer ou récupérer une instance existante."""
    resp = requests.post(
        f"{_launcher_url()}/instance/create",
        json={"user_id": user_id, "challenge_id": challenge_id},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_instance_info_for_user(user_id: int, challenge_id: str) -> dict:
    """Récupère l'état de l'instance de cet utilisateur pour ce challenge."""
    resp = requests.get(
        f"{_launcher_url()}/instance/status",
        params={"user_id": user_id, "challenge_id": challenge_id},
        timeout=5,
    )
    resp.raise_for_status()
    return resp.json()


def stop_instance_for_user(user_id: int, challenge_id: str) -> dict:
    """Demande au launcher d'arrêter l'instance de cet utilisateur."""
    resp = requests.post(
        f"{_launcher_url()}/instance/stop",
        json={"user_id": user_id, "challenge_id": challenge_id},
        timeout=5,
    )
    resp.raise_for_status()
    return resp.json()

# ---------------------------------------------------------------------------
# Routes HTTP exposées par le plugin à CTFd
# ---------------------------------------------------------------------------

@instance_bp.route("/launch/<int:challenge_id>", methods=["POST"])
@bypass_csrf_protection
@authed_only
def launch_instance(challenge_id: int):
    """
    Lance (ou retrouve) l'instance pour l'utilisateur courant.
    Réponse JSON : { status, port, expires_at, host }
    """
    user      = get_current_user()
    challenge = Challenges.query.get(challenge_id)

    if not challenge:
        return jsonify({"status": "error", "message": "Challenge introuvable"}), 404

    # Vérifie que ce challenge supporte le launcher via son tag
    tag_values = [t.value.lower() for t in challenge.tags]
    if _launcher_tag() not in tag_values:
        return jsonify({
            "status": "error",
            "message": f"Ce challenge ne supporte pas le launcher (tag '{_launcher_tag()}' absent)",
        }), 400

    try:
        result = launch_instance_for_user(user.id, str(challenge_id))
        if result.get("status") == "ok":
            result["host"] = result.get("host") or _ctf_host()
        return jsonify(result)

    except requests.ConnectionError:
        log.error("Impossible de joindre le launcher sur %s", _launcher_url())
        return jsonify({"status": "error", "message": "Launcher indisponible"}), 503

    except Exception:
        log.exception("Erreur lors du lancement de l'instance")
        return jsonify({"status": "error", "message": "Erreur interne"}), 500


@instance_bp.route("/status/<int:challenge_id>", methods=["GET"])
@authed_only
def instance_status(challenge_id: int):
    """
    Retourne l'état de l'instance courante.
    Réponse JSON : { status, port, expires_at, host } ou { status: "not_found" }
    """
    user = get_current_user()

    try:
        result = get_instance_info_for_user(user.id, str(challenge_id))
        if result.get("status") == "ok":
            result["host"] = result.get("host") or _ctf_host()
        return jsonify(result)

    except requests.ConnectionError:
        return jsonify({"status": "error", "message": "Launcher indisponible"}), 503

    except Exception:
        log.exception("Erreur lors de la récupération du statut")
        return jsonify({"status": "error", "message": "Erreur interne"}), 500


@instance_bp.route("/stop/<int:challenge_id>", methods=["POST"])
@bypass_csrf_protection
@authed_only
def stop_instance(challenge_id: int):
    """
    Arrête l'instance de l'utilisateur courant.
    Réponse JSON : { status }
    """
    user = get_current_user()

    try:
        result = stop_instance_for_user(user.id, str(challenge_id))
        return jsonify(result)

    except requests.ConnectionError:
        return jsonify({"status": "error", "message": "Launcher indisponible"}), 503

    except Exception:
        log.exception("Erreur lors de l'arrêt de l'instance")
        return jsonify({"status": "error", "message": "Erreur interne"}), 500


# ---------------------------------------------------------------------------
# Point d'entrée du plugin (appelé par CTFd au démarrage)
# ---------------------------------------------------------------------------

def load(app):
    app.register_blueprint(instance_bp)

    # Sert les assets statiques du plugin (JS)
    register_plugin_assets_directory(
        app, base_path="/plugins/instance_launcher/assets/"
    )

    # Injecte le script sur toutes les pages utilisateur
    register_plugin_script(
        "/plugins/instance_launcher/assets/instance_launcher.js"
    )

    log.info(
        "Plugin instance_launcher chargé — launcher: %s, tag: '%s', host: %s",
        _launcher_url(), _launcher_tag(), _ctf_host(),
    )
