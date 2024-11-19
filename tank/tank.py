from pathlib import Path
import threading
import paho.mqtt.client as PahoMQTT
import time
from queue import Queue
import json
import requests

P = Path(__file__).parent.absolute()
SETTINGS = P / 'settings.json'

class TankSimulator:
    """Tank simulator that listens to water monitoring that gives command to water the plant
        In simulation watering is done by incrementing moisture in a mathematical way"""
    def __init__(self, simId,  baseTopic, plantCode, jarVolume, tankCapacity):
        self.simId = simId
        self.active = True
        self.isOn = True
        self.tankCapacity = tankCapacity #liters
        self.tankLevel = tankCapacity #liters
        self.jarVolume = jarVolume
        self.pubTopic = baseTopic + "/tank"
        self.subTopic = baseTopic + "/waterPump/+" 
        self.plantCode = plantCode
        self.aliveTopic = baseTopic + "/alive"
        self.aliveBn = "updateCatalogDevice"
        self.myPub = MyPublisher(self.simId + "TankPub", self.pubTopic)
        self.mySub = MySubscriber(self.simId + "TankSub", self.subTopic)
        self.myPub.start()
        self.mySub.start()
        
    def stop(self):
        self.mySub.stop()
        self.myPub.stop()
    def setActiveFalse(self):
        self.active = False
    def setActiveTrue(self):
        self.active = True
        

class MyPublisher:
    def __init__(self, clientID, topic):
        self.clientID = clientID  + "water_pump"
        self.topic = topic
		# create an instance of paho.mqtt.client
        self._paho_mqtt = PahoMQTT.Client(self.clientID, False) 
		# register the callback
        self._paho_mqtt.on_connect = self.myOnConnect
        try:
            with open(SETTINGS, "r") as fs:                
                self.settings = json.loads(fs.read())            
        except Exception:
            print("Problem in loading settings")
        self.messageBroker = self.settings["messageBroker"]
        self.port = self.settings["brokerPort"]

    def start (self):
		#manage connection to broker
        self._paho_mqtt.connect(self.messageBroker, self.port)
        self._paho_mqtt.loop_start()

    def stop (self):
        self._paho_mqtt.loop_stop()
        self._paho_mqtt.disconnect()

    def myPublish(self, message, topic):
		# publish a message with a certain topic
        self._paho_mqtt.publish(topic, message, 2)

    def myOnConnect (self, paho_mqtt, userdata, flags, rc):
        print ("Connected to %s with result code: %d, pubtopic: %s" % (self.messageBroker, rc,self.topic))

class MySubscriber:
    def __init__(self, clientID, topic):
        self.clientID = clientID +  "water_pump_sub"
        self.q = Queue()
		# create an instance of paho.mqtt.client
        self._paho_mqtt = PahoMQTT.Client(self.clientID, False) 
		# register the callback
        self._paho_mqtt.on_connect = self.myOnConnect
        self._paho_mqtt.on_message = self.myOnMessageReceived
        try:
            with open(SETTINGS, "r") as fs:                
                self.settings = json.loads(fs.read())            
        except Exception:
            print("Problem in loading settings")
        self.messageBroker = self.settings["messageBroker"]
        self.port = self.settings["brokerPort"]
        self.qos = self.settings["qos"]
        self.topic = topic

    def start (self):
		#manage connection to broker
        self._paho_mqtt.connect(self.messageBroker, self.port)
        self._paho_mqtt.loop_start()
		# subscribe for a topic
        self._paho_mqtt.subscribe(self.topic, self.qos)

    def stop (self):
        self._paho_mqtt.unsubscribe(self.topic)
        self._paho_mqtt.loop_stop()
        self._paho_mqtt.disconnect()

    def myOnConnect (self, paho_mqtt, userdata, flags, rc):
        print ("Connected to %s with result code: %d, subtopic: %s" % (self.messageBroker, rc,self.topic))

    def myOnMessageReceived (self, paho_mqtt , userdata, msg):
		# A new message is received
        self.q.put(msg)
        # print ("Topic:'" + msg.topic+"', QoS: '"+str(msg.qos)+"' Message: '"+str(msg.payload) + "'")


def update_simulators(simulators):
    """Function that update simulators based on plant catalog changes"""
    try:
        with open(SETTINGS, "r") as fs:                
            settings = json.loads(fs.read())            
    except Exception:
        print("Problem in loading settings")
    url = settings["registry_url"] + "/plants"
    modelsUrl = settings["registry_url"] + "/models"
    response = requests.get(url)
    plants = json.loads(response.text)
    responseModels = requests.get(modelsUrl)
    models = json.loads(responseModels.text)
    for plant in plants:
        simId = plant["plantCode"]
        simId
        found = 0
        for sim in simulators:
            if sim.simId == simId:
                found = 1
        if found == 0:
            for mod in models:
                if simId.startswith(mod["model_code"]):
                    jarVolume = mod["jar_volume"]
                    tankCapacity = mod["tank_capacity"]
            baseTopic = "RootyPy/" + plant["userId"] + "/" + plant["plantCode"]
            sim = TankSimulator(simId, baseTopic, plant["plantCode"], jarVolume, tankCapacity)
            simulators.append(sim)
    for sim in simulators:
        found = 0
        for plant in plants:            
            sensId = plant["plantCode"]
            if sim.simId == sensId:
                found = 1
        if found == 0:
            simulators.remove(sim)

def main():
    simulators = []

    while True:
        update_simulators(simulators)
        litersToGive = 0
        for sim in simulators:
            if not sim.mySub.q.empty():
                msg = sim.mySub.q.get()
                if msg is None:
                    continue
                else:
                    mess = json.loads(msg.payload)
                    print("\n\n\nMessage from water irrigator:\n",mess)
                    print(msg.topic,"\n")
                    if mess['bn'] == "refillTank":
                        sim.tankLevel = sim.tankCapacity
                    else:
                        litersToGive = mess["e"][0]["v"]
                if litersToGive < sim.tankLevel:
                    event = {"n": "irrigation", "u": "VWC", "t": str(time.time()), 
                        "v": litersToGive/sim.jarVolume*100}
                    sim.tankLevel -= litersToGive
                    event1 = {"n": "tankLevel", "u": "l", "t": str(time.time()), 
                        "v": sim.tankLevel}
                    out = {"bn": sim.pubTopic,"e":[event, event1]}
                    print(out)
                    sim.myPub.myPublish(json.dumps(out), sim.pubTopic)
                elif sim.tankLevel > 0 and litersToGive > sim.tankLevel:
                    event = {"n": "irrigation", "u": "VWC", "t": str(time.time()), 
                        "v": sim.tankLevel/sim.jarVolume*100}
                    sim.tankLevel = float(0)
                    event1 = {"n": "tankLevel", "u": "l", "t": str(time.time()), 
                        "v": sim.tankLevel}
                    out = {"bn": sim.pubTopic,"e":[event, event1]}
                    print(out)
                    sim.myPub.myPublish(json.dumps(out), sim.pubTopic)
                else:
                    event = {"n": "irrigation", "u": "VWC", "t": str(time.time()), 
                        "v": float(0)}
                    sim.tankLevel = float(0)
                    event1 = {"n": "tankLevel", "u": "l", "t": str(time.time()), 
                        "v": sim.tankLevel}
                    out = {"bn": sim.pubTopic,"e":[event, event1]}
                    print(out)
                    sim.myPub.myPublish(json.dumps(out), sim.pubTopic)
                    #send message to user to fill the tank
                    print(f"Insufficient water in tank {sim.simId}, requested water {litersToGive}")
            eventAlive = {"n": sim.plantCode + "/tank", "u": "IP", "t": str(time.time()), "v": ""}
            outAlive = {"bn": sim.aliveBn,"e":[eventAlive]}
            sim.myPub.myPublish(json.dumps(outAlive), sim.aliveTopic)
        time.sleep(10)

    

if __name__ == '__main__':

    main()