"""
Gestion du cycle de vie des instances de challenges.

Règles :
  - Une seule instance active par (user_id, challenge_id)
  - Durée de vie maximale : INSTANCE_TIMEOUT secondes (15 min par défaut)
  - Si l'instance existe mais que le processus est mort → nettoyage transparent
  - Un thread de fond (CleanupThread) supprime les instances expirées toutes
    les 30 s sans intervention manuelle

Chaque challenge doit fournir un exécutable en mode STDIN/STDOUT (pas de --port).
Le launcher démarre un bridge Python qui expose un port TCP et relie chaque client
au programme challenge via stdin/stdout.
Structure attendue sur le disque :
    $CTF_CHALLENGES_DIR/<challenge_id>/server_binary
"""

import logging
import os
import signal
import sqlite3
import subprocess
import sys
import time

from cleanup import CleanupThread
from port_allocator import PortAllocator

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (surcharge possible via variables d'environnement)
# ---------------------------------------------------------------------------
INSTANCE_TIMEOUT  = int(os.environ.get("CTF_INSTANCE_TIMEOUT", 15 * 60))  # 15 min
CHALLENGES_DIR    = os.environ.get("CTF_CHALLENGES_DIR", "/opt/ctf/challenges")

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DB_PATH   = os.path.join(BASE_DIR, "state.db")
LOGS_DIR  = os.path.join(BASE_DIR, "logs")
BRIDGE_PATH = os.path.join(BASE_DIR, "stdio_port_bridge.py")

# Délai (s) avant SIGKILL après un SIGTERM
SIGTERM_GRACE = 3


# ---------------------------------------------------------------------------
# InstanceManager
# ---------------------------------------------------------------------------

class InstanceManager:

    def __init__(self):
        self.port_allocator = PortAllocator()
        self._init_db()
        self._restore_state()
        # Lance le nettoyage en arrière-plan
        self._cleanup_thread = CleanupThread(self)
        self._cleanup_thread.start()
        log.info("InstanceManager initialisé (DB: %s)", DB_PATH)

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS instances (
                    instance_key  TEXT    PRIMARY KEY,
                    user_id       INTEGER NOT NULL,
                    challenge_id  TEXT    NOT NULL,
                    port          INTEGER NOT NULL,
                    pid           INTEGER NOT NULL,
                    started_at    REAL    NOT NULL,
                    expires_at    REAL    NOT NULL
                )
            """)
            conn.commit()

    def _restore_state(self) -> None:
        """
        Au redémarrage du service, relit la DB pour :
          - marquer les ports des instances encore vivantes comme occupés
          - supprimer les entrées dont le processus est mort
        """
        now = time.time()
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT instance_key, pid, port FROM instances WHERE expires_at > ?",
                (now,),
            ).fetchall()

        for key, pid, port in rows:
            if self._pid_alive(pid):
                self.port_allocator.mark_used(port)
                log.info("Instance restaurée au démarrage : %s (pid=%d port=%d)", key, pid, port)
            else:
                log.info("Instance morte détectée au démarrage, nettoyage : %s", key)
                self._delete_row(key)

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def create_instance(self, user_id: int, challenge_id: str) -> dict:
        """
        Crée une nouvelle instance ou retourne l'existante si elle est encore active.

        Retourne : { port: int, expires_at: float }
        Lève    : FileNotFoundError si le binaire est absent
                  RuntimeError      si plus aucun port n'est disponible
        """
        # Nettoyage préventif avant chaque création
        self.cleanup_expired()

        existing = self.find_instance(user_id, challenge_id)
        if existing:
            log.info(
                "Instance existante retournée (user=%d challenge=%s)", user_id, challenge_id
            )
            return existing

        binary_path = os.path.join(CHALLENGES_DIR, challenge_id, "server_binary")
        if not os.path.isfile(binary_path):
            raise FileNotFoundError(f"Binaire introuvable : {binary_path}")
        if not os.path.isfile(BRIDGE_PATH):
            raise FileNotFoundError(f"Bridge introuvable : {BRIDGE_PATH}")

        port       = self.port_allocator.allocate()
        now        = time.time()
        expires_at = now + INSTANCE_TIMEOUT
        key        = self._make_key(user_id, challenge_id)

        os.makedirs(LOGS_DIR, exist_ok=True)
        log_path = os.path.join(LOGS_DIR, f"instance_{key.replace(':', '_')}.log")

        with open(log_path, "a") as log_file:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    BRIDGE_PATH,
                    "--listen-port",
                    str(port),
                    "--exec",
                    binary_path,
                ],
                stdout=log_file,
                stderr=log_file,
                close_fds=True,
                # Isole le processus pour qu'un Ctrl+C sur le launcher ne le tue pas
                start_new_session=True,
                cwd=os.path.dirname(binary_path),
            )

        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO instances VALUES (?, ?, ?, ?, ?, ?, ?)",
                (key, user_id, challenge_id, port, proc.pid, now, expires_at),
            )
            conn.commit()

        log.info(
            "Instance créée : user=%d challenge=%s port=%d pid=%d expire=%s",
            user_id, challenge_id, port, proc.pid,
            time.strftime("%H:%M:%S", time.localtime(expires_at)),
        )
        return {"port": port, "expires_at": expires_at}

    def find_instance(self, user_id: int, challenge_id: str) -> dict | None:
        """
        Retourne { port, expires_at } si une instance valide existe,
        sinon None.
        Nettoie automatiquement si le processus est mort.
        """
        key = self._make_key(user_id, challenge_id)
        now = time.time()

        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT port, pid, expires_at FROM instances "
                "WHERE instance_key = ? AND expires_at > ?",
                (key, now),
            ).fetchone()

        if not row:
            return None

        port, pid, expires_at = row

        if not self._pid_alive(pid):
            log.info("Process mort détecté pour %s → nettoyage", key)
            self._delete_row(key)
            self.port_allocator.release(port)
            return None

        return {"port": port, "expires_at": expires_at}

    def stop_instance(self, user_id: int, challenge_id: str) -> bool:
        """
        Arrête et supprime l'instance.
        Retourne True si trouvée et arrêtée, False sinon.
        """
        key = self._make_key(user_id, challenge_id)

        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT pid, port FROM instances WHERE instance_key = ?", (key,)
            ).fetchone()

        if not row:
            return False

        pid, port = row
        self._kill_pid(pid)
        self._delete_row(key)
        self.port_allocator.release(port)
        log.info("Instance arrêtée manuellement : user=%d challenge=%s", user_id, challenge_id)
        return True

    def cleanup_expired(self) -> int:
        """
        Supprime toutes les instances expirées OU dont le processus est mort.
        Retourne le nombre d'instances nettoyées.
        Appelé périodiquement par CleanupThread et avant chaque création.
        """
        now     = time.time()
        cleaned = 0

        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT instance_key, pid, port, expires_at FROM instances"
            ).fetchall()

        for key, pid, port, expires_at in rows:
            if expires_at <= now or not self._pid_alive(pid):
                self._kill_pid(pid)
                self._delete_row(key)
                self.port_allocator.release(port)
                cleaned += 1
                log.info("Instance nettoyée : %s (expiré=%s)", key, expires_at <= now)

        return cleaned

    # ------------------------------------------------------------------
    # Méthodes internes
    # ------------------------------------------------------------------

    @staticmethod
    def _make_key(user_id: int, challenge_id: str) -> str:
        return f"{user_id}:{challenge_id}"

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        """Vérifie si le processus existe encore (signal 0)."""
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    @staticmethod
    def _kill_pid(pid: int) -> None:
        """Envoie SIGTERM, puis SIGKILL après le délai de grâce."""
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return  # Processus déjà mort

        # Attente de l'arrêt propre
        for _ in range(SIGTERM_GRACE * 10):
            time.sleep(0.1)
            if not InstanceManager._pid_alive(pid):
                return

        # Toujours vivant → force kill
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    @staticmethod
    def _delete_row(key: str) -> None:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM instances WHERE instance_key = ?", (key,))
            conn.commit()
