from dotenv import load_dotenv
load_dotenv()
from core.mongo_client import MongoClient

m = MongoClient()
m.connect()
runs = list(m._db['backtest_runs'].find().sort('created_at', -1).limit(1))
for r in runs:
    print(r)