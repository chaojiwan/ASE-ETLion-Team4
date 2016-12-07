import time
import numbers
import urllib2
import unittest

from flask import Flask
from engineio import server

from ETLionServer import app, socketio
from ETLionServer import index, trade, signup, login, logout
from ETLionServer import background_thread_place_order


class ETLionServerTestCase(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.app.config.update(
            dict(
                TESTING = True,
                EMAIL = 'test@test.com',
                PASSWORD = 'testtest',
                ORDER_DISCOUNT = 10,
                ORDER_SIZE = 200,
                INVENTORY = 1000,
                TRADING_FREQ = 5
            )
        )
        self.tester = self.app.test_client()

    def tearDown(self):
        self.logout()

    def index(self):
        return self.tester.get('/')
    
    def login(self, email, password):
        return self.tester.post(
            '/login',
            data=dict(
                email=email,
                password=password
            ),
            follow_redirects=True
        )

    def logout(self):
        return self.tester.get('/logout', follow_redirects=True)

    def trade(self):
        return self.tester.get('/calculate', )
    
    def test_index(self):
        response = self.index()
        self.assertEqual(response.status_code, 200)
        self.assertTrue("Welcome to ETLion Trading System!" in response.data)

    def test_login(self):
        self.logout()
        response = self.login(
            self.app.config["EMAIL"],
            self.app.config["PASSWORD"]
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse("Welcome to ETLion Trading System!" in response.data)
        self.assertTrue("Hi, Trader" in response.data)
        self.logout()
        response = self.login(
            self.app.config["EMAIL"] + 'x',
            self.app.config["PASSWORD"] + 'x'
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue("Log in" in response.data)
    
    def test_logout(self):
        response = self.logout()
        self.assertEqual(response.status_code, 200)
        self.assertTrue("Welcome to ETLion Trading System!" in response.data)
        self.assertFalse("Hi, Trader" in response.data)

    def test_trade(self):
        self.login(
            self.app.config["EMAIL"],
            self.app.config["PASSWORD"]
        )
        self.socketio_tester = socketio.test_client(self.app)
        post_params = {
            "order_discount": self.app.config["ORDER_DISCOUNT"],
            "order_size": self.app.config["ORDER_SIZE"],
            "inventory": self.app.config["INVENTORY"],
            "trading_frequency": self.app.config["TRADING_FREQ"],
            "is_for_test": True
        }
        self.socketio_tester.emit("calculate", post_params)
        receiveds = self.socketio_tester.get_received()
        self.assertEqual(
            len(receiveds),
            self.app.config["INVENTORY"] / self.app.config["ORDER_SIZE"]
        )
        for received in receiveds:
            self.assertTrue(
                bool(received["args"])
            )
            self.assertTrue(
                isinstance(
                    received["args"][0]["discount_price"], 
                    numbers.Real
                )
            )
            self.assertTrue(
                isinstance(
                    received["args"][0]["notional"], 
                    numbers.Real
                )
            )
            self.assertTrue(
                isinstance(
                    received["args"][0]["pnl"], 
                    numbers.Real
                )
            )
            self.assertTrue(
                isinstance(
                    received["args"][0]["share_price"], 
                    numbers.Real
                )
            )
            self.assertEqual(
                received["args"][0]["total_qty"],
                self.app.config["INVENTORY"]
            )
            self.assertEqual(
                received["args"][0]["order_size"],
                self.app.config["ORDER_SIZE"]
            )
            self.assertEqual(
                received["name"],
                "trade_log"
            )
        
if __name__ == "__main__":
    unittest.main()