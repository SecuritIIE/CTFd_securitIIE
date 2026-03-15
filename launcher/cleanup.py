"""
Thread de nettoyage des instances expirées.

Tourne en arrière-plan (daemon) et appelle manager.cleanup_expired()
toutes les CLEANUP_INTERVAL secondes pour tuer les processus expirés
et libérer les ports associés.
"""

import logging
import threading

log = logging.getLogger(__name__)

CLEANUP_INTERVAL = 30  # secondes entre deux passages de nettoyage


class CleanupThread(threading.Thread):
    """
    Thread daemon qui nettoie périodiquement les instances expirées.
    S'arrête proprement via stop().
    """

    def __init__(self, manager):
        super().__init__(name="ctf-cleanup", daemon=True)
        self.manager = manager
        self._stop_event = threading.Event()

    def run(self) -> None:
        log.info(
            "Thread de nettoyage démarré (intervalle : %ds)", CLEANUP_INTERVAL
        )
        # _stop_event.wait() retourne True si l'événement est positionné,
        # False si le timeout expire → on continue la boucle jusqu'au stop().
        while not self._stop_event.wait(timeout=CLEANUP_INTERVAL):
            try:
                count = self.manager.cleanup_expired()
                if count:
                    log.info(
                        "Nettoyage : %d instance(s) expirée(s) supprimée(s)", count
                    )
            except Exception:
                log.exception("Erreur dans le thread de nettoyage")

        log.info("Thread de nettoyage arrêté")

    def stop(self) -> None:
        """Demande l'arrêt propre du thread."""
        self._stop_event.set()
