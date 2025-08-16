from flask import Flask, Response
from threading import Thread

app = Flask("keep_alive")

@app.route("/ping-x92a7f", methods=["GET", "HEAD"])
def ping():
    print("Ping received!")  # Logs every hit
    return Response("Bot is alive!", status=200)

def keep_alive():
    def run():
        # Bind to 0.0.0.0 so Render can route traffic
        app.run(host="0.0.0.0", port=8080)
    Thread(target=run).start()
