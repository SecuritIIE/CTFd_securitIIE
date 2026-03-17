"""
Allocateur de ports thread-safe.

Réserve dynamiquement un port libre dans la plage CTF_PORT_START–CTF_PORT_END
(défaut : 30000–40000). Utilise un ensemble interne pour éviter les conflits
entre allocations concurrentes et s'appuie sur un bind() réel pour vérifier
que le port est libre au niveau système.
"""

import os
import random
import socket
import threading

PORT_RANGE_START = int(os.environ.get("CTF_PORT_START", 30000))
PORT_RANGE_END   = int(os.environ.get("CTF_PORT_END",   40000))


class PortAllocator:
    """Thread-safe : alloue le premier port libre dans la plage configurée."""

    def __init__(self):
        self._lock  = threading.Lock()
        self._used: set[int] = set()

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def allocate(self) -> int:
        """
        Retourne un port libre et le marque comme utilisé.
        Lève RuntimeError si toute la plage est épuisée.
        """
        with self._lock:
            candidates = list(range(PORT_RANGE_START, PORT_RANGE_END))
            random.SystemRandom().shuffle(candidates)
            for port in candidates:
                if port not in self._used and self._is_port_free(port):
                    self._used.add(port)
                    return port

        raise RuntimeError(
            f"Aucun port libre dans la plage {PORT_RANGE_START}–{PORT_RANGE_END}"
        )

    def release(self, port: int) -> None:
        """Libère un port précédemment alloué."""
        with self._lock:
            self._used.discard(port)

    def mark_used(self, port: int) -> None:
        """
        Marque un port comme occupé sans l'allouer (utilisé au démarrage
        pour rétablir l'état depuis la base de données).
        """
        with self._lock:
            self._used.add(port)

    # ------------------------------------------------------------------
    # Interne
    # ------------------------------------------------------------------

    @staticmethod
    def _is_port_free(port: int) -> bool:
        """Tente un bind() réel pour confirmer que le port est disponible."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("0.0.0.0", port))
                return True
            except OSError:
                return False
