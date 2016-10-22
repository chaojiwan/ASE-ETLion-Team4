import json
import time
import random
import urllib2

from Enum import POST, GET
from Enum import ORDER_DISCOUNT, ORDER_SIZE, INVENTORY, TRADING_FREQUENCY
from Enum import QUERY_URL, ORDER_URL


class ETLionCore(object):
    def __init__(self, **kwargs):
        print kwargs
        self.order_discount = int(kwargs["order_discount"])
        self.order_size = int(kwargs["order_size"])
        self.inventory = int(kwargs["inventory"])
        self.trading_freq = int(kwargs["trading_frequency"])

    def trade(self):
        # Start with all shares and no profit
        qty = self.inventory
        pnl = 0

        # Repeat the strategy until we run out of shares.
        while qty > 0:
            # Query the price once every N seconds.
            time.sleep(self.trading_freq)

            quote = json.loads(urllib2.urlopen(QUERY_URL.format(random.random())).read())
            price = float(quote['top_bid']['price'])
            print "Quoted at %s" % price

            # Attempt to execute a sell order.
            order_args = (self.order_size, price - self.order_discount)
            print "Executing 'sell' of {:,} @ {:,}".format(*order_args)
            url   = ORDER_URL.format(random.random(), *order_args)
            order = json.loads(urllib2.urlopen(url).read())

            # Update the PnL if the order was filled.
            if order['avg_price'] > 0:
                price    = order['avg_price']
                notional = float(price * self.order_size)
                pnl += notional
                qty -= self.order_size
                print "Sold {:,} for ${:,}/share, ${:,} notional".format(self.order_size, price, notional)
                print "PnL ${:,}, Qty {:,}".format(pnl, qty)
            else:
                print "Unfilled order; $%s total, %s qty" % (pnl, qty)

            time.sleep(1)