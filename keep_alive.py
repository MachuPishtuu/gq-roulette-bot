from flask import Flask, Response
from threading import Thread
from datetime import datetime

app = Flask("keep_alive")

@app.route("/ping-x92a7f", methods=["GET", "HEAD"])
def ping():
    print(f"[{datetime.utcnow()}] Ping received!")
    return Response("Bot is alive!", status=200)

def keep_alive():
    # Run Flask in a separate thread so Discord bot can run concurrently
    server = Thread(target=lambda: app.run(host="0.0.0.0", port=8080))
    server.daemon = True  # Thread will close when main program exits
    server.start()
