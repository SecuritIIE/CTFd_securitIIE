#!/usr/bin/env python3
"""
Bridge TCP <-> STDIN/STDOUT pour challenges.

Usage:
  python stdio_port_bridge.py --listen-port 31000 --exec /opt/ctf/challenges/3/server_binary

Comportement:
  - Le bridge écoute sur un port TCP.
  - À chaque connexion, il lance l'exécutable challenge (sans --port)
    et relie:
      socket client -> stdin challenge
      stdout/stderr challenge -> socket client
"""

import argparse
import os
import signal
import socket
import subprocess
import threading
from typing import Optional

STOP_EVENT = threading.Event()


def socket_to_stdin(sock: socket.socket, proc: subprocess.Popen) -> None:
    try:
        while not STOP_EVENT.is_set():
            data = sock.recv(4096)
            if not data:
                break
            if proc.stdin:
                proc.stdin.write(data)
                proc.stdin.flush()
    except Exception:
        pass
    finally:
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass


def stdout_to_socket(sock: socket.socket, proc: subprocess.Popen) -> None:
    try:
        if not proc.stdout:
            return
        while not STOP_EVENT.is_set():
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            sock.sendall(chunk)
    except Exception:
        pass


def handle_client(client: socket.socket, exec_path: str) -> None:
    with client:
        proc: Optional[subprocess.Popen] = None
        try:
            proc = subprocess.Popen(
                [exec_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                cwd=os.path.dirname(exec_path) or None,
                close_fds=True,
            )

            t_in = threading.Thread(target=socket_to_stdin, args=(client, proc), daemon=True)
            t_out = threading.Thread(target=stdout_to_socket, args=(client, proc), daemon=True)
            t_in.start()
            t_out.start()

            proc.wait()
            t_in.join(timeout=0.2)
            t_out.join(timeout=0.2)
        finally:
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=1)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument("--exec", dest="exec_path", required=True)
    args = parser.parse_args()

    exec_path = os.path.abspath(args.exec_path)
    if not os.path.isfile(exec_path):
        raise FileNotFoundError(exec_path)

    def _signal_handler(_signum, _frame):
        STOP_EVENT.set()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", args.listen_port))
        srv.listen(50)
        srv.settimeout(1.0)

        while not STOP_EVENT.is_set():
            try:
                client, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            threading.Thread(target=handle_client, args=(client, exec_path), daemon=True).start()


if __name__ == "__main__":
    main()
