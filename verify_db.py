from pymongo import MongoClient

MONGO_URI = None
with open("files.txt", "r") as f:
    for line in f:
        if line.strip().startswith("uri ="):
            MONGO_URI = line.split('=', 1)[1].strip().strip('"')
            break

if MONGO_URI:
    client = MongoClient(MONGO_URI)
    db = client.nifty_shop

    print("--- Trades (trades_test) ---")
    for trade in db.trades_test.find():
        print(trade)

    print("\n--- Logs (logs_test) ---")
    for log in db.logs_test.find():
        print(log)
else:
    print("Could not find MongoDB URI in files.txt")
