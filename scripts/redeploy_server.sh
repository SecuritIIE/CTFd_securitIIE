#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCHER_SRC="$REPO_DIR/launcher"
LAUNCHER_DST="/opt/ctf/launcher"
CHALLENGES_DST="/opt/ctf/challenges"
SERVICE_SRC="$REPO_DIR/launcher/ctf-launcher.service"
SERVICE_DST="/etc/systemd/system/ctf-launcher.service"
CTF_USER="ctf"
RESTART_CTFD=1
BUILD_CTFD=1
VENV_PYTHON="$LAUNCHER_DST/venv/bin/python"
DOCKER_COMPOSE_CMD=()

usage() {
  cat <<'EOF'
Usage: ./scripts/redeploy_server.sh [options]

Options:
  --skip-ctfd        Ne relance pas le conteneur CTFd
  --no-build         Fait un `docker compose up -d` sans rebuild
  --no-pull          N'exécute pas `git pull --ff-only`
  -h, --help         Affiche cette aide

Ce script :
  1. fait git pull du dépôt
  2. recopie launcher/ vers /opt/ctf/launcher
  3. installe/met à jour le service systemd ctf-launcher
  4. crée/met à jour le venv Python du launcher
  5. redémarre ctf-launcher
  6. relance CTFd via docker compose (par défaut)
EOF
}

DO_PULL=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-ctfd)
      RESTART_CTFD=0
      shift
      ;;
    --no-build)
      BUILD_CTFD=0
      shift
      ;;
    --no-pull)
      DO_PULL=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Option inconnue: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

log() {
  printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Commande requise introuvable: $1" >&2
    exit 1
  fi
}

ensure_docker_compose() {
  require_cmd docker

  if ! sudo docker info >/dev/null 2>&1; then
    log "Démarrage du service docker"
    sudo systemctl enable docker >/dev/null 2>&1 || true
    sudo systemctl start docker >/dev/null 2>&1 || true
  fi

  if ! sudo docker info >/dev/null 2>&1; then
    echo "Docker est installé mais le démon ne répond pas." >&2
    echo "Vérifiez le service avec: sudo systemctl status docker" >&2
    exit 1
  fi

  if sudo docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE_CMD=(sudo docker compose)
    return
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE_CMD=(sudo docker-compose)
    return
  fi

  echo "Docker Compose est introuvable." >&2
  echo "Installez le plugin 'docker compose' ou le binaire 'docker-compose', puis relancez le script." >&2
  exit 1
}

require_cmd git
require_cmd python3
require_cmd sudo

cd "$REPO_DIR"

if [[ $DO_PULL -eq 1 ]]; then
  log "Mise à jour du dépôt git"
  git pull --ff-only
fi

log "Création des dossiers de déploiement"
sudo mkdir -p "$LAUNCHER_DST" "$CHALLENGES_DST"

log "Copie du launcher"
sudo cp -a "$LAUNCHER_SRC"/. "$LAUNCHER_DST"/

log "Installation du service systemd"
sudo install -m 644 "$SERVICE_SRC" "$SERVICE_DST"

if ! id "$CTF_USER" >/dev/null 2>&1; then
  log "Création de l'utilisateur système $CTF_USER"
  sudo useradd --system --no-create-home --shell /usr/sbin/nologin "$CTF_USER"
fi

log "Permissions launcher"
sudo chown -R "$CTF_USER:$CTF_USER" "$LAUNCHER_DST"

log "Virtualenv Python du launcher"
if [[ ! -x "$VENV_PYTHON" ]]; then
  sudo -u "$CTF_USER" python3 -m venv "$LAUNCHER_DST/venv"
fi

if ! sudo -u "$CTF_USER" "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
  log "Bootstrap de pip dans le virtualenv"
  if ! sudo -u "$CTF_USER" "$VENV_PYTHON" -m ensurepip --upgrade >/dev/null 2>&1; then
    echo "Impossible d'installer pip dans $LAUNCHER_DST/venv." >&2
    echo "Installez le paquet système python3-venv (et éventuellement python3-pip), puis relancez le script." >&2
    exit 1
  fi
fi

sudo -u "$CTF_USER" "$VENV_PYTHON" -m pip install --upgrade pip
sudo -u "$CTF_USER" "$VENV_PYTHON" -m pip install -r "$LAUNCHER_DST/requirements.txt"

log "Redémarrage du service ctf-launcher"
sudo systemctl daemon-reload
sudo systemctl enable ctf-launcher >/dev/null 2>&1 || true
sudo systemctl restart ctf-launcher
sudo systemctl --no-pager --full status ctf-launcher || true

if [[ $RESTART_CTFD -eq 1 ]]; then
  ensure_docker_compose
  log "Relance de CTFd via docker compose"
  if [[ $BUILD_CTFD -eq 1 ]]; then
    "${DOCKER_COMPOSE_CMD[@]}" up -d --build
  else
    "${DOCKER_COMPOSE_CMD[@]}" up -d
  fi
fi

log "Vérification santé du launcher"
python3 - <<'PY'
import json
import urllib.request

for url in (
    "http://127.0.0.1:5001/health",
    "http://host.docker.internal:5001/health",
):
    try:
        data = urllib.request.urlopen(url, timeout=3).read().decode()
        print(f"OK {url} -> {data}")
    except Exception as exc:
        print(f"WARN {url} -> {exc}")
PY

log "Déploiement terminé"
