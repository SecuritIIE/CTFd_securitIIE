/**
 * CTFd Plugin — Instance Launcher
 * ================================
 * Injecte automatiquement un panneau "Lancer une instance" dans le modal de
 * challenge pour les challenges qui portent le tag configuré (défaut : "instance").
 *
 * Flux :
 *   1. MutationObserver surveille l'insertion du HTML du challenge dans le modal
 *   2. Si le challenge a le bon tag → injecte le panneau
 *   3. Vérifie d'emblée si une instance est déjà active (GET /status)
 *   4. Bouton "Lancer" → POST /launch → affiche "nc <host> <port>"
 *   5. Bouton "Arrêter" → POST /stop → réaffiche le bouton "Lancer"
 *
 * Le tag à chercher et le prefixe des routes viennent des data-attributes
 * injectés par le plugin Python (ou on utilise les valeurs par défaut).
 */
(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  // Configuration (peut être surchargée via data-attributes sur <body>)
  // ---------------------------------------------------------------------------
  const LAUNCHER_TAG    = (document.body.dataset.launcherTag    || "instance").toLowerCase();
  const ROUTES_PREFIX   = "/plugins/instance_launcher";

  // ---------------------------------------------------------------------------
  // Rendu de l'UI
  // ---------------------------------------------------------------------------

  /**
   * Retourne le sélecteur du panneau #challenge à l'intérieur du modal actif.
   * Fonctionne avec le thème core (Alpine.js) et le thème core-deprecated (jQuery).
   */
  function getChallengePanel() {
    return (
      document.querySelector("#challenge-window #challenge") ||
      document.querySelector("[x-ref='challengeWindow'] #challenge") ||
      document.querySelector(".modal.show #challenge")
    );
  }

  /**
   * Récupère l'id du challenge depuis les données Alpine.js ou en parsant x-init.
   */
  function getChallengeId(modalEl) {
    const el = modalEl.querySelector("[x-data='Challenge']");
    if (!el) return null;

    // Méthode Alpine.js directe
    if (window.Alpine) {
      try {
        const data = Alpine.$data(el);
        if (data && data.id) return data.id;
      } catch (_) {}
    }

    // Fallback : parse x-init="id = 42; ..."
    const xInit = el.getAttribute("x-init") || "";
    const match = xInit.match(/\bid\s*=\s*(\d+)/);
    return match ? parseInt(match[1], 10) : null;
  }

  /**
   * Extrait les tags visibles du modal actuellement affiché.
   */
  function getVisibleTags(modalEl) {
    return Array.from(
      modalEl.querySelectorAll(".challenge-tag")
    ).map((el) => el.textContent.trim().toLowerCase());
  }

  // ---------------------------------------------------------------------------
  // Injection du panneau dans le modal
  // ---------------------------------------------------------------------------

  function injectLauncherPanel(modalEl) {
    const challengeId = getChallengeId(modalEl);
    if (!challengeId) return;

    const panel = getChallengePanel();
    if (!panel) return;

    // Déjà injecté ?
    if (document.getElementById(`instance-launcher-${challengeId}`)) return;

    // Ce challenge porte-t-il le tag requis ?
    if (!getVisibleTags(modalEl).includes(LAUNCHER_TAG)) return;

    const container = document.createElement("div");
    container.id        = `instance-launcher-${challengeId}`;
    container.className = "instance-launcher mt-3 text-center";
    container.innerHTML = `
      <hr class="my-3">
      <div id="instance-info-${challengeId}">
        <p class="text-muted small mb-2">Ce challenge nécessite une instance dédiée.</p>
        <button class="btn btn-primary btn-sm" id="launch-btn-${challengeId}">
          🚀 Lancer une instance
        </button>
      </div>
    `;

    panel.appendChild(container);

    // Attache l'event une fois le bouton dans le DOM
    document
      .getElementById(`launch-btn-${challengeId}`)
      .addEventListener("click", () => CTFdLauncher.launch(challengeId));

    // Vérifie immédiatement si une instance tourne déjà
    CTFdLauncher.checkStatus(challengeId);
  }

  // ---------------------------------------------------------------------------
  // API publique : CTFdLauncher
  // ---------------------------------------------------------------------------

  window.CTFdLauncher = {

    launch(challengeId) {
      const info = document.getElementById(`instance-info-${challengeId}`);
      if (!info) return;
      info.innerHTML = `
        <span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
        Lancement en cours…
      `;

      fetch(`${ROUTES_PREFIX}/launch/${challengeId}`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
      })
        .then((r) => r.json())
        .then((data) => {
          if (data.status === "ok") {
            CTFdLauncher._showRunning(challengeId, data.host, data.port, data.expires_at);
          } else {
            CTFdLauncher._showError(challengeId, data.message || "Erreur inconnue");
          }
        })
        .catch(() => CTFdLauncher._showError(challengeId, "Impossible de contacter le launcher"));
    },

    stop(challengeId) {
      const info = document.getElementById(`instance-info-${challengeId}`);
      if (!info) return;
      info.innerHTML = `
        <span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
        Arrêt en cours…
      `;

      fetch(`${ROUTES_PREFIX}/stop/${challengeId}`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
      })
        .then((r) => r.json())
        .then(() => CTFdLauncher._showStopped(challengeId))
        .catch(() => CTFdLauncher._showError(challengeId, "Impossible d'arrêter l'instance"));
    },

    checkStatus(challengeId) {
      fetch(`${ROUTES_PREFIX}/status/${challengeId}`, {
        credentials: "same-origin",
      })
        .then((r) => r.json())
        .then((data) => {
          if (data.status === "ok") {
            CTFdLauncher._showRunning(challengeId, data.host, data.port, data.expires_at);
          }
        })
        .catch(() => {}); // silencieux : pas d'instance active
    },

    // -----------------------------------------------------------------------
    // Rendus internes
    // -----------------------------------------------------------------------

    _showRunning(challengeId, host, port, expiresAt) {
      const info = document.getElementById(`instance-info-${challengeId}`);
      if (!info) return;

      const expiresDate = new Date(expiresAt * 1000);
      const timeStr     = expiresDate.toLocaleTimeString();

      info.innerHTML = `
        <div class="alert alert-success d-inline-block py-2 px-3 text-start mb-2">
          <strong>Instance active !</strong><br>
          <code class="fs-6">nc ${host} ${port}</code><br>
          <small class="text-muted">Expire à ${timeStr}</small>
        </div>
        <div>
          <button class="btn btn-danger btn-sm" id="stop-btn-${challengeId}">
            ⏹ Arrêter l'instance
          </button>
        </div>
      `;

      document
        .getElementById(`stop-btn-${challengeId}`)
        .addEventListener("click", () => CTFdLauncher.stop(challengeId));
    },

    _showStopped(challengeId) {
      const info = document.getElementById(`instance-info-${challengeId}`);
      if (!info) return;
      info.innerHTML = `
        <p class="text-muted small mb-2">Instance arrêtée.</p>
        <button class="btn btn-primary btn-sm" id="launch-btn-${challengeId}">
          🚀 Lancer une instance
        </button>
      `;
      document
        .getElementById(`launch-btn-${challengeId}`)
        .addEventListener("click", () => CTFdLauncher.launch(challengeId));
    },

    _showError(challengeId, message) {
      const info = document.getElementById(`instance-info-${challengeId}`);
      if (!info) return;
      info.innerHTML = `
        <div class="alert alert-danger py-2 px-3 d-inline-block">❌ ${message}</div>
        <div class="mt-2">
          <button class="btn btn-secondary btn-sm" id="retry-btn-${challengeId}">
            Réessayer
          </button>
        </div>
      `;
      document
        .getElementById(`retry-btn-${challengeId}`)
        .addEventListener("click", () => CTFdLauncher.launch(challengeId));
    },
  };

  // ---------------------------------------------------------------------------
  // MutationObserver — surveille l'ouverture du modal de challenge
  // ---------------------------------------------------------------------------

  function startObserver() {
    // Le modal peut avoir deux sélecteurs selon la version du thème
    const modalEl =
      document.getElementById("challenge-window") ||
      document.querySelector("[x-ref='challengeWindow']");

    if (!modalEl) return;

    const observer = new MutationObserver(() => {
      // Légère pause pour laisser Alpine.js terminer son rendu
      requestAnimationFrame(() => injectLauncherPanel(modalEl));
    });

    observer.observe(modalEl, { childList: true, subtree: false });
  }

  // ---------------------------------------------------------------------------
  // Initialisation
  // ---------------------------------------------------------------------------

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startObserver);
  } else {
    startObserver();
  }
})();
