import threading
import paho.mqtt.client as mqtt
import json
from requests.exceptions import HTTPError
import time
import requests

class water_pump(object):
    """
    Class representing the water pump functionality.

    Attributes:
        clientID (str): The client ID for MQTT connection.
        broker (str): The MQTT broker.
        port (int): The MQTT port.
        sub_topic (list): List of MQTT subscription topics.
        pub_topic (str): The MQTT publication topic.
        client (mqtt.Client): The MQTT client.
        plants (None): Placeholder for plants data.
        code_db (None): Placeholder for code database.
        url_plants (str): The URL for plants data.
        url_models (str): The URL for code models data.
        url_devices (str): The URL for devices data.
        pump (dict): The pump data.
    """
    def __init__(self , config):
        """
        Initializes the light_shift object.

        Args:
            config (dict): Configuration data for light_shift.
        """
        self.manual_init_hour = None
        self.manual_final_hour = None
        self.clientID = config["ID_water_pump"]
        self.broker = config["broker"]
        self.port = config["port"]
        self.sub_topic = config["sub_topics_water_pump"] 
        self.client = mqtt.Client(self.clientID, True)
        self.client.on_connect = self.myconnect
        self.client.on_message = self.mymessage
        self.plants = None
        self.code_db = None
        self.url_plants = config["url_plants"]
        self.url_models = config["url_models"]
        self.url_devices = config["url_devices"]

    def start_mqtt(self):
        """
        Starts the MQTT connection and control state thread.
        """
        self.client.connect(self.broker,self.port)
        self.client.loop_start()
        for topic in self.sub_topic:
            self.client.subscribe(topic, 2)

    def get_response(self,url):
        """
        Sends a GET request to the specified URL and returns the response.
        It tries 15 times to get the response, if it fails it returns an empty list.

        Args:
            url (str): The URL to send the GET request to.
        """
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
   
    def mymessage(self,paho_mqtt,userdata,msg):
        '''
        it takes the message from the broker and publish the state of the pump
        it takes the flow from the message and publish it
        '''
        mess = json.loads(msg.payload)
        pump = { "bn": "None","e": [
        {
            "n": "Volume of water",
            "u": "l",
            "t": "None",
            "v": "None"
        }
    ]}
        topic = msg.topic
        topic_parts = topic.split("/")  
        last_part = topic_parts[-1]  
        current_user = topic_parts[1]
        current_plant = topic_parts[2]
        getpump = self.GetPump(current_plant)
        if getpump == True:
            flow = mess['e'][0]['v']
            if float(flow) > 0:
                flow = float(flow)
            else: 
                flow = 0
            if last_part == "automatic":
                pub_topic = "RootyPy/"+topic_parts[1]+"/"+topic_parts[2]+"/waterPump/automatic"
                pump["e"][0]["v"] = flow
                pump["e"][0]["t"] = time.time()
                pump["bn"] = "pump_state"
                print("State of the pump :" + str(pump) + "\nstate = "+\
                    "\n" + str(pub_topic))
                self.publish(pump,pub_topic)
                time.sleep(0.5)  

            elif last_part == "manual":
            
                pump["e"][0]["v"] = flow
                pump["e"][0]["t"] = time.time()
                pump["bn"] = "pump_state"
                pub_topic = "RootyPy/"+topic_parts[1]+"/"+topic_parts[2]+"/waterPump/manual"
                print("State of the pump :" + str(pump) + "\nstate = "+\
                    "\n" + str(pub_topic) )
                self.publish(pump,pub_topic)
                time.sleep(0.5)  

        else: print(f"No pump found for the {current_user} and {current_plant}")

    def myconnect(self,paho_mqtt, userdata, flags, rc):
       print(f"water pump: Connected to {self.broker} with result code {rc} \n subtopic {self.sub_topic}")

    def publish(self, pump, pub_topic):
       pump=json.dumps(pump)
       self.client.publish(pub_topic,pump,2)

    def CodeRequest(self):
        """
        It gets the plant code from the database from the server.
        """

        self.code_db=self.get_response(f"{self.url_models}")

    def GetPump(self,plantcode):
        """
        Checks if a pump is available for the current user and plant.

        Returns:
            bool: True if a pump is found, False otherwise.
        """
        try:
            self.pump = self.get_response(self.url_devices)
            self.plants = self.get_response(self.url_plants)

            for lamp in self.pump:
                ID = lamp["deviceID"]
                ID_split = ID.split("/")
                type = ID_split[1]
                if ID_split[0] == plantcode and \
                    type == "tank":
                    print(f"\nFind a pump for plant {plantcode}")
                    return True
            return False
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
            return False


    
        
class run():
    """ this class is used to run the water_pump and the Iamalive class in parallel"""

    def __init__(self, ThreadID, name,config):
        self.ThreadID = ThreadID
        self.name = name
        self.water_pump = water_pump(config)
        self.water_pump.start_mqtt()
        self.alive = Iamalive(config)
        self.alive.start_mqtt()
        self.alive_interval = config["alive_interval"]


    def run(self):
        '''
        the iamalive thread is started and the water_pump thread is started
        iamalive is send every alive_interval seconds
        '''
        try:
            while True:
                self.alive.publish()  
                time.sleep(self.alive_interval)
        except KeyboardInterrupt:
                self.water_pump.stop()
                self.alive.stop()

class Iamalive(object):
    "I am alive"

    def __init__(self , config):

        self.clientID = config["ID_Iamalive"]
        self.broker = config["broker"]
        self.port = config["port"]
        self.sub_topic = config["sub_topic_Iamalive"] 
        self.pub_topic = config["pub_topic_Iamalive"]
        self.client = mqtt.Client(self.clientID, True)
        self.time = time.time()
        self.client.on_connect = self.myconnect
        self.message = {"bn": "updateCatalogService",\
                        "e":\
                        [{ "n": "water_irrigator", "u": "", "t": self.time, "v":"water_irrigator" }]}
    
    def start_mqtt(self):
        self.client.connect(self.broker,self.port)
        self.client.loop_start()


    def myconnect(self,paho_mqtt, userdata, flags, rc):
       print(f"Iamalive: Connected to {self.broker} with result code {rc} \n subtopic {self.sub_topic}")

    def publish(self):
        self.message["e"][0]["t"]= time.time()
        __message=json.dumps(self.message)
        print(__message)
        print(self.pub_topic, self.broker, self.port)
        self.client.publish(topic=self.pub_topic,payload=__message,qos=2)


if __name__=="__main__":    
    config = json.load(open("config_water_irrigator.json","r"))
    main = run(3, "Mqtt",config)
    print("> Starting light shift...")
    main.run()