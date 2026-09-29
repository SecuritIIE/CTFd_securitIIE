# Déploiement des challenges dynamiques — CTFd-Whale

Le launcher maison (`launcher/` + plugin `instance_launcher`) a été remplacé par
[CTFd-Whale](https://github.com/frankli0324/ctfd-whale). Whale spawn un container
(ou un groupe) par joueur, via **Docker Swarm**, et les expose via **frp** :

- **direct** : `nc ctf.securitiie.iiens.net <port>` (plage `10000-10100`)
- **http**   : `http://<uuid>.ctf.securitiie.iiens.net:8001/`

## Ce qui est déjà configuré dans le repo

- Plugin vendored dans `CTFd/plugins/ctfd-whale/` (deps ajustées pour CTFd 3.8.2).
- Services `frps` + `frpc` et réseaux overlay `frp_connect` / `frp_containers`
  dans `docker-compose.yml` (projet nommé `ctfd`).
- Conf frp : `conf/frp/frps.ini` et `conf/frp/frpc.ini` (token partagé).
- Config Whale pré-remplie (`CTFd/plugins/ctfd-whale/utils/setup.py`) :
  réseau `ctfd_frp_containers`, ports directs `10000-10100`, http `8001`,
  domaine `ctf.securitiie.iiens.net`. Appliquée automatiquement au 1er démarrage.

## Étapes à faire sur le serveur (une seule fois)

1. **Initialiser Swarm et labelliser le nœud** (obligatoire pour Whale) :
   ```bash
   docker swarm init
   docker node update --label-add 'name=linux-1' $(docker node ls -q)
   ```
   (`linux-1` = valeur de `whale:docker_swarm_nodes`.)

2. **Ouvrir la plage de ports directs** dans le firewall :
   ```bash
   sudo ufw allow 10000:10100/tcp
   ```

3. **(challenges http) DNS wildcard** : faire pointer
   `*.ctf.securitiie.iiens.net` vers le serveur, et proxifier vers `frps:8001`.
   Un bloc nginx type :
   ```nginx
   server {
     listen 443 ssl;
     server_name *.ctf.securitiie.iiens.net;
     # ... certs letsencrypt wildcard ...
     location / {
       proxy_pass http://frps:8001;
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
     }
   }
   ```

4. **Build + up** :
   ```bash
   docker compose build ctfd
   docker compose up -d
   ```

5. **Vérifier frp** : `docker compose logs frpc` doit afficher
   `login to server success` et `admin server listen on ...`.

6. **Vérifier Whale** : admin CTFd → menu **Whale** → `/plugins/ctfd-whale/admin/settings`.
   La page ne doit afficher **aucune erreur** (Docker API + frpc joignables).
   Sinon, `docker network ls -f "label=com.docker.compose.project=ctfd" --format "{{.Name}}"`
   pour confirmer le nom du réseau et l'ajuster dans la config Whale.

## Créer un challenge à instance

Admin → Challenges → **Create** → type **`dynamic_docker`**. Renseigner l'image
Docker, le port interne, et le mode (`direct` / `http`). L'image doit lire la
variable d'env `FLAG` au démarrage (voir la doc Whale « Challenge Deployment »).

## Sécurité

- Le token frp (`conf/frp/*.ini`) est un secret partagé committé : à régénérer
  (`python3 -c "import secrets;print(secrets.token_hex(16))"`) et remplacer dans
  les deux `.ini` si le repo devient public.
- `ctfd` tourne en `root` pour accéder au socket Docker (requis par Whale).
