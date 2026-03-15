#!/usr/bin/env python3
import sys


FLAG = "securitiieCTF{BTIiXvM04i7%4fQKMMcc}"


def send(msg: str) -> None:
    sys.stdout.write(msg)
    sys.stdout.flush()


def main() -> None:
    send("Bonjour! Tape 'flag' pour obtenir le flag.\n")
    while True:
        send("> ")
        line = sys.stdin.readline()
        if not line:
            return

        cmd = line.strip().lower()
        if cmd == "flag":
            send(f"{FLAG}\n")
        elif cmd in {"quit", "exit"}:
            send("bye\n")
            return
        else:
            send("Commande inconnue. Utilise: flag\n")


if __name__ == "__main__":
    main()
