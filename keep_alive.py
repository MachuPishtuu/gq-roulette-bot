from flask import Flask
from threading import Thread
import os

app = Flask(__name__)

# Secret keep-alive path so only you & UptimeRobot can access
SECRET_PATH = os.environ.get("KEEP_ALIVE_PATH", "ping-7h3sj3")  # random default

@app.route(f"/{SECRET_PATH}")
def home():
    return "OK", 200

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()
