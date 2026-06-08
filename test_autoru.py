import logging, sys
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout)
from parsers.autoru import parse
r = parse()
print(f"Auto.ru: {len(r)}")
for x in r[:40]:
    print(f"  {x['title']} | {x['price']:,} руб | id={x['listing_id']}")
