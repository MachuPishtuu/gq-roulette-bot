from flask import Flask, Response

app = Flask("keep_alive")

@app.route("/ping-x92a7f", methods=["GET", "HEAD"])
def ping():
    return Response("Bot is alive!", status=200)

def keep_alive():
    from threading import Thread
    server = Thread(target=lambda: app.run(host="0.0.0.0", port=8080))
    server.start()
