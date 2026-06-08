import logging, sys
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout)
from parsers.drom import parse
r = parse()
print(f"ИТОГО: {len(r)} объявлений")
for x in r[:40]:
    print(f"  {x['title']} | {x['price']:,} руб | {x['city']}")
