"""LocalMind gateway: the always-on half of LocalMind, for a small server on the same network.

It's the page you open on your phone. It remembers your chats and the PC's last status, wakes the
PC with a Wake-on-LAN packet when you send a message, waits for LocalMind to start, then passes
the message on and streams the answer back.
"""
