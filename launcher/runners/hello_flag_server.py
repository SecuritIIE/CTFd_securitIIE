#!/usr/bin/env python3
import argparse
import socket
import threading


def handle_client(conn: socket.socket):
    with conn:
        conn.sendall(b"Bonjour! Tape 'flag' pour obtenir le flag.\n")
        conn.sendall(b"> ")

        while True:
            data = conn.recv(1024)
            if not data:
                return

            cmd = data.decode(errors="ignore").strip().lower()
            if cmd == "flag":
                conn.sendall(b"securitiieCTF{BTIiXvM04i7%4fQKMMcc}\n")
            elif cmd in {"quit", "exit"}:
                conn.sendall(b"bye\n")
                return
            else:
                conn.sendall(b"Commande inconnue. Utilise: flag\n")

            conn.sendall(b"> ")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", args.port))
    srv.listen(50)

    while True:
        conn, _addr = srv.accept()
        t = threading.Thread(target=handle_client, args=(conn,), daemon=True)
        t.start()


if __name__ == "__main__":
    main()
