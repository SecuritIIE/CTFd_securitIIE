"""
CTF Instance Launcher — Service HTTP local
-------------------------------------------
Par défaut, écoute sur 127.0.0.1:5001.

Si CTFd tourne en Docker et le launcher sur l'hôte, configure:
    - CTF_BIND_HOST=0.0.0.0 (ou IP de l'interface docker, ex. 172.17.0.1)
    - CTF_BIND_PORT=5001

Puis côté CTFd:
    - LAUNCHER_URL=http://host.docker.internal:5001

Routes :
  POST /instance/create  { user_id, challenge_id }  → { status, port, expires_at }
  GET  /instance/status  ?user_id=&challenge_id=     → { status, port, expires_at } ou { status: "not_found" }
  POST /instance/stop    { user_id, challenge_id }  → { status }
"""

import logging
import os
import sys

from flask import Flask, jsonify, request

# Permet de lancer le script directement depuis son dossier
sys.path.insert(0, os.path.dirname(__file__))

from instance_manager import InstanceManager

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOGS_DIR, "launcher.log")),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)
manager = InstanceManager()

BIND_HOST = os.environ.get("CTF_BIND_HOST", "127.0.0.1")
BIND_PORT = int(os.environ.get("CTF_BIND_PORT", "5001"))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/instance/create", methods=["POST"])
def create_instance():
    """Crée ou retourne l'instance existante pour (user_id, challenge_id)."""
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("user_id")
    challenge_id = data.get("challenge_id")

    if not user_id or not challenge_id:
        return jsonify({"status": "error", "message": "user_id et challenge_id sont requis"}), 400

    try:
        result = manager.create_instance(int(user_id), str(challenge_id))
        return jsonify({"status": "ok", **result})

    except FileNotFoundError as exc:
        log.error("Binaire introuvable pour le challenge '%s': %s", challenge_id, exc)
        return jsonify({"status": "error", "message": "Binaire du challenge introuvable"}), 404

    except RuntimeError as exc:
        log.error("Erreur lors de la création de l'instance: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 503

    except Exception:
        log.exception("Erreur inattendue dans /instance/create")
        return jsonify({"status": "error", "message": "Erreur interne du launcher"}), 500


@app.route("/instance/status", methods=["GET"])
def get_instance_status():
    """Retourne l'état de l'instance pour (user_id, challenge_id)."""
    user_id = request.args.get("user_id", type=int)
    challenge_id = request.args.get("challenge_id")

    if not user_id or not challenge_id:
        return jsonify({"status": "error", "message": "user_id et challenge_id sont requis"}), 400

    result = manager.find_instance(user_id, str(challenge_id))
    if result:
        return jsonify({"status": "ok", **result})
    return jsonify({"status": "not_found"})


@app.route("/instance/stop", methods=["POST"])
def stop_instance():
    """Arrête et supprime l'instance pour (user_id, challenge_id)."""
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("user_id")
    challenge_id = data.get("challenge_id")

    if not user_id or not challenge_id:
        return jsonify({"status": "error", "message": "user_id et challenge_id sont requis"}), 400

    stopped = manager.stop_instance(int(user_id), str(challenge_id))
    if stopped:
        return jsonify({"status": "ok"})
    return jsonify({"status": "not_found"})


@app.route("/health", methods=["GET"])
def health():
    """Healthcheck rapide."""
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Entrée principale
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    log.info("CTF Instance Launcher démarré sur %s:%d", BIND_HOST, BIND_PORT)
    app.run(host=BIND_HOST, port=BIND_PORT, debug=False, threaded=True)
