from pathlib import Path
import threading
import paho.mqtt.client as PahoMQTT
import time
from queue import Queue
import json
import requests
from requests.exceptions import HTTPError

P = Path(__file__).parent.absolute()
SETTINGS = P / 'settings.json'

def get_request(url):
    """Make a request to the url specified with retries"""
    for i in range(15):
            try:
                response = requests.get(url)
                response.raise_for_status()
                return json.loads(response.text)
            except HTTPError as http_err:
                print(f"HTTP error occurred: {http_err}")
            except Exception as err:
                print(f"Other error occurred: {err}")
            time.sleep(1)
    return []

class MoistureSens:
    """Simulation class for moisture sensor"""
    def __init__(self, sensorId, decreaseCoef, currentState, baseTopic, plantCode):
        self.sensorId = sensorId
        self.decayCoef = decreaseCoef
        self.currentState = currentState
        self.active = True
        self.pubTopic = baseTopic + "/moisture"
        self.subTopic = baseTopic + "/tank" 
        self.aliveBn = "updateCatalogDevice"
        self.plantCode = plantCode
        self.aliveTopic = baseTopic + "/alive"
        self.myPub = MyPublisher(self.sensorId + "Pub", self.pubTopic)
        self.mySub = MySubscriber(self.sensorId + "Sub", self.subTopic)
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
        self.clientID = clientID  + "moisture"
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
        self.qos = self.settings["qos"]

    def start (self):
		#manage connection to broker
        self._paho_mqtt.connect(self.messageBroker, self.port)
        self._paho_mqtt.loop_start()

    def stop (self):
        self._paho_mqtt.loop_stop()
        self._paho_mqtt.disconnect()

    def myPublish(self, message, topic):
		# publish a message with a certain topic
        self._paho_mqtt.publish(topic, message, self.qos)

    def myOnConnect (self, paho_mqtt, userdata, flags, rc):
        print ("Connected to %s with result code: %d" % (self.messageBroker, rc))
        print("Client ID: ",self.clientID)

class MySubscriber:
	
    def __init__(self, clientID, topic):
        self.clientID = clientID  + "moisturesub"
        self.q = Queue()
        # create an instance of paho.mqtt.client
        self._paho_mqtt = PahoMQTT.Client(self.clientID, False) 
        # register the callback
        self._paho_mqtt.on_connect = self.myOnConnect
        self._paho_mqtt.on_message = self.myOnMessageReceived
        self.topic = topic
        try:
            with open(SETTINGS, "r") as fs:                
                self.settings = json.loads(fs.read())            
        except Exception:
            print("Problem in loading settings")
        self.messageBroker = self.settings["messageBroker"]
        self.port = self.settings["brokerPort"]
        self.qos = self.settings["qos"]

    def start (self):
		#manage connection to broker
        self._paho_mqtt.connect(self.messageBroker, 1883)
        self._paho_mqtt.loop_start()
        # subscribe for a topic
        self._paho_mqtt.subscribe(self.topic, self.qos)

    def stop (self):
        self._paho_mqtt.unsubscribe(self.topic)
        self._paho_mqtt.loop_stop()
        self._paho_mqtt.disconnect()
    
    def myOnConnect (self, paho_mqtt, userdata, flags, rc):
        print ("Connected to %s with result code: %d" % (self.messageBroker, rc))

    def myOnMessageReceived (self, paho_mqtt , userdata, msg):
		# A new message is received
        self.q.put(msg)
        print ("Topic:'" + msg.topic+"', QoS: '"+str(msg.qos)+"' Message: '"+str(msg.payload) + "'")

def update_sensors(sensors):
    """Update the sensors list in case of changes to the catalog"""
    try:
        with open(SETTINGS, "r") as fs:                
            settings = json.loads(fs.read())            
    except Exception:
        print("Problem in loading settings")
    test = settings["test"]
    plants = get_request(settings["registry_url"] + "/plants")
    plantTypes = get_request(settings["registry_url"] + "/valid_plant_types")
    for plant in plants:
        sensId = plant["plantCode"]
        found = 0
        for sens in sensors:
            if sens.sensorId == sensId:
                found = 1
        if found == 0:
            decayCoeff = 0
            for types in plantTypes:
                if types["type"] == plant["type"]:
                    decayCoeff = types["moistureDecay"]
            if test == 1:
                """For test we multiply the decayCoefficent, non realistical"""
                decayCoeff *= 600
            baseTopic = "RootyPy/" + plant["userId"] + "/" + plant["plantCode"]
            sens = MoistureSens(sensId, decayCoeff, 100, baseTopic, plant["plantCode"])
            sensors.append(sens)
    for sens in sensors:
        found = 0
        for plant in plants:
            sensId = plant["plantCode"]
            if sens.sensorId == sensId:
                found = 1
        if found == 0:
            sensors.remove(sens)


def main():
    sensors = []

    while True:
        update_sensors(sensors)
        for sens in sensors:
            waterQuantity = 0
            if not sens.mySub.q.empty():
                msg = sens.mySub.q.get()
                if msg is None:
                    continue
                else:
                    payload = json.loads(msg.payload.decode("utf-8"))
                    waterQuantity += float(payload['e'][0]['v'])  
            sens.currentState += waterQuantity                   
            event = {"n": "moisture", "u": "VWC", "t": str(time.time()), "v": float(sens.currentState)}#VolumetricWaterContent
            out = {"bn": sens.pubTopic,"e":[event]}
            print(out)
            sens.myPub.myPublish(json.dumps(out), sens.pubTopic)
            eventAlive = {"n": sens.plantCode+"/moisture", "u": "IP", "t": str(time.time()), "v": ""}
            outAlive = {"bn": sens.aliveBn ,"e":[eventAlive]}
            print(outAlive)
            sens.myPub.myPublish(json.dumps(outAlive), sens.aliveTopic)
            sens.currentState -= sens.decayCoef
            if sens.currentState<0:
                sens.currentState=0
        time.sleep(10)

if __name__ == '__main__':

    main()