from ibapi.client import EClient
from ibapi.wrapper import EWrapper
import threading
import time

class TestApp(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
        self.connected = False

    def nextValidId(self, orderId):
        self.connected = True
        print(f"✅ Conectado. Next order ID: {orderId}")
        self.reqAccountSummary(9001, "All", "NetLiquidation,TotalCashValue,AvailableFunds")

    def accountSummary(self, reqId, account, tag, value, currency):
        print(f"   {account} | {tag}: {value} {currency}")

    def accountSummaryEnd(self, reqId):
        print("✅ Done.")
        self.disconnect()

    def error(self, reqId, errorCode, errorString, advancedJson=""):
        if errorCode not in (2104, 2106, 2107, 2108, 2158):
            print(f"❌ [{errorCode}] {errorString}")

app = TestApp()
app.connect("127.0.0.1", 4004, clientId=20260305)

thread = threading.Thread(target=app.run)
thread.start()

# Espera hasta 30s a que conecte
for i in range(30):
    time.sleep(1)
    if not thread.is_alive():
        break

thread.join(timeout=5)