import paho.mqtt.client as mqtt
import json
import numpy as np
from requests.exceptions import HTTPError
import time
import datetime
import threading
import requests

class light_shift(object):
    """
    Class representing the light shift functionality.

    Attributes:
        manual_init_hour (float): The initial hour for manual light shift.
        manual_final_hour (float): The final hour for manual light shift.
        state (int): The state of the light shift (0 for automatic, 1 for manual).
        current_user (str): The current user.
        current_plant (str): The current plant.
        list_of_manual_plant (list): List of manual plants.
        max_lux (float): The maximum lux value.
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
        lamp (dict): The lamp data.
    """

    def __init__(self , config):
        """
        Initializes the light_shift object.

        Args:
            config (dict): Configuration data for light_shift.
        """
        self.manual_init_hour = 0.0
        self.manual_final_hour = 0.0
        self.state = 0 # 0 automatic | 1 manual
        self.current_user = None
        self.current_plant = None
        self.list_of_manual_plant = [] 
        self.max_lux = None # 
        self.clientID = config["ID_light_shift"]
        self.broker = config["broker"]
        self.port = config["port"]
        self.sub_topic = config["sub_topics_light_shift"] 
        self.pub_topic = config["pub_topic_light_shift"]
        self.client = mqtt.Client(self.clientID, True)
        self.client.on_connect = self.myconnect
        self.client.on_message = self.mymessage
        self.plants = None
        self.code_db = None
        self.url_plants = config["url_plants"]
        self.url_models = config["url_models"]
        self.url_devices = config["url_devices"]
        self.lamp = { "bn": "None","e": [
        {
            "n": "current_intensity",
            "u": "percentage",
            "t": "None",
            "v": "None"
        },
        {
            "n": "init_hour",
            "u": "s",
            "t": "None",
            "v": "None"
        },
        {
            "n": "final_hour",
            "u": "s",
            "t": "None",
            "v": "None"
        }
    ]}
        

    def start_mqtt(self):
        """
        Starts the MQTT connection and control state thread.
        """
        self.client.connect(self.broker,self.port)
        self.client.loop_start()
        control_thread = threading.Thread(target=self.control_state)
        control_thread.start()
        for topic in self.sub_topic:
            self.client.subscribe(topic, 2)

    def control_state(self):
        """
        Controls that the lamp in manual mode come back in automatic mode when the time is expired.
        When the time is expired the lamp is turned off and the lamp is removed from the list.
        """
        while True:
            for j,user in enumerate(self.list_of_manual_plant):
                if time.time() >= int(user["e"][3]["v"]) and \
                time.time() <= int(user["e"][4]["v"]):
                    self.state = 1
                else:
                    self.state = 0
                    self.lamp["e"][0]["v"] = 0.0
                    self.lamp["e"][1]["v"] = 0.0
                    self.lamp["e"][2]["v"] = 0.0
                    us = self.list_of_manual_plant[j]["e"][0]["v"]
                    plant = self.list_of_manual_plant[j]["e"][1]["v"]
                    self.pub_topic = "RootyPy/"+us+"/"+plant+"/lightShift/automatic"
                    self.publish(self.lamp)
                    del self.list_of_manual_plant[j]
                    

            print("\nDict:\n" + str(self.list_of_manual_plant) + "\n")
            time.sleep(2)
            

    def mymessage(self,paho_mqtt,userdata,msg):
        '''
        this function is called when a message is received on the subscribed topic
        it takes a message from automatic or manual light shift and publish the new state of the lamp
        if the message is manual, it adds the plant to the list of manual plants, if it is already in the list, it updates the state
        '''
        
        mess = json.loads(msg.payload)
        print(mess)
        self.lamp = { "bn": "None","e": [
        {
            "n": "current_intensity",
            "u": "percentage",
            "t": "None",
            "v": "None"
        },
        {
            "n": "init_hour",
            "u": "s",
            "t": "None",
            "v": "None"
        },
        {
            "n": "final_hour",
            "u": "s",
            "t": "None",
            "v": "None"
        }
    ]
}
        topic = msg.topic
        topic_parts = topic.split("/")  
        last_part = topic_parts[-1] 
        self.current_user = topic_parts[1]
        self.current_plant = topic_parts[2]
        self.state = 0

        self.getlamp = self.GetLamp()
        if self.getlamp == True:
            self.get_plant_jar()

            for user in self.list_of_manual_plant:
                if user["e"][1]['v'] == self.current_plant and user["e"][0]["v"] == self.current_user:
                    self.state = 1 
            
            self.intensity = float(mess['e'][0]['v'])
            if last_part == "automatic" and self.state == 0:

                if float(self.intensity) > 0:
                    if float(self.intensity) >= self.max_lux:
                        self.intensity = self.max_lux
                    else:
                        self.intensity = float(self.intensity)
                else: 
                    self.intensity = 0.0
                self.pub_topic = "RootyPy/"+topic_parts[1]+"/"+topic_parts[2]+"/lightShift/automatic"
                self.lamp["e"][0]["v"] = float(round(self.intensity*100/self.max_lux))
                self.lamp["e"][1]["v"] = 0.0
                self.lamp["e"][2]["v"] = 0.0
                self.lamp["e"][0]["t"] = time.time()
                self.lamp["e"][1]["t"] = time.time()
                self.lamp["e"][2]["t"] = time.time()
                self.lamp["bn"] = "lamp_state"
                print("\nState of the lamp :" + str(self.lamp) + "\nstate = " +str(self.state) +\
                    "\n" + str(self.pub_topic)+ "\nmax lux: " + str(self.max_lux)) # + "\ncode: "  + str(self.code_db)
                self.publish(self.lamp)
                

            elif last_part == "manual":

                self.manual_init_hour = float(mess["e"][1]["v"])
                self.manual_final_hour = float(mess["e"][2]["v"])
                self.lamp["e"][0]["v"] = self.intensity
                self.lamp["e"][1]["v"] = self.manual_init_hour
                self.lamp["e"][2]["v"] = self.manual_final_hour
                self.lamp["e"][0]["t"] = time.time()
                self.lamp["e"][1]["t"] = time.time()
                self.lamp["e"][2]["t"] = time.time()
                self.lamp["bn"] = "lamp_state"
                self.check_manuals(self.lamp)
                
                
                self.pub_topic = "RootyPy/"+topic_parts[1]+"/"+topic_parts[2]+"/lightShift/manual"
                print("\nState of the lamp :" + str(self.lamp) + "\nstate = " +str(self.state) +\
                    "\n" + str(self.pub_topic) + "\nmax lux: " + str(self.max_lux))
                self.publish(self.lamp)

        else: print(f"No lamp found for the {self.current_user} and {self.current_plant}")

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

    def myconnect(self,paho_mqtt, userdata, flags, rc):
       print(f"light shift: Connected to {self.broker} with result code {rc} \n subtopic {self.sub_topic}, pubtopic {self.pub_topic}")

    def publish(self, lamp):
       lamp=json.dumps(lamp)
       self.client.publish(self.pub_topic,lamp,2)

    
    def CodeRequest(self):
        """
        It gets the plant code from the database from the server.
        """

        self.code_db = self.get_response(self.url_models)


    def GetLamp(self):
        """
        Checks if a lamp is available for the current user and plant.

        Returns:
            bool: True if a lamp is found, False otherwise.
        """
        try:

            self.lamps = self.get_response(self.url_devices)
            self.plants = self.get_response(self.url_plants)

            for lamp in self.lamps:
                ID = lamp["deviceID"]
                ID_split = ID.split("/")
                plantcode = ID_split[0]
                type = ID_split[1]

                for plant in self.plants:
                    if plant['plantCode'] == plantcode and self.current_user == plant['userId'] and \
                        type == "lampLight":
                        print(f"Find a lamp for user {self.current_user} and plant {plantcode}")
                        return True
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
            return False


    def get_plant_jar(self):
        """
        From the plant code, gets the maximum lux value of the lamp
        """

        self.plants = self.get_response(self.url_plants)

        for plant in self.plants:
            if plant['userId'] == self.current_user:
                if plant['plantCode'] == self.current_plant:
                    current_code = plant['plantCode']
                    current_model = current_code[0:2]
                    self.CodeRequest()
                    for code in self.code_db:
                        if code["model_code"] == current_model:
                            self.max_lux = code["max_lux"]
                            return
                    print(f"No plant code found for {current_model}")
        print(f"\nNo plant found for {self.current_user}/{self.current_plant}")

    
    def check_manuals(self,lamp):

        """
        Checks if the lamp is already in the list of manual plants, if there is update it's state, otherwise add it to the list.
        """

        for j,user in enumerate(self.list_of_manual_plant):
            if self.current_user == user["e"][0]["v"] and self.current_plant == user["e"][1]["v"]:
                self.list_of_manual_plant[j] = {"bn": self.current_user + "/" + self.current_plant,\
                                            "e":\
                                            [{ "n": "user", "u": None, "t": time.time(), "v":self.current_user }, \
                                             { "n": "plant", "u": None, "t": time.time(), "v":self.current_plant }, \
                                             { "n": "state", "u": "boleean", "t": time.time(), "v": 1 }, \
                                             { "n": "init_hour", "u": "s", "t": time.time(), "v":self.manual_init_hour }, \
                                             { "n": "final_hour", "u": "s", "t": time.time(), "v":self.manual_final_hour }, \
                                             { "n": "current_intensity", "u": "percentage", "t": time.time(), "v":lamp["e"][0]["v"] }  \
                                             ]}

                return
            
        self.list_of_manual_plant.append({"bn": self.current_user + "/" + self.current_plant,\
                                        "e":\
                                        [{ "n": "user", "u": None, "t": time.time(), "v":self.current_user }, \
                                            { "n": "plant", "u": None, "t": time.time(), "v":self.current_plant }, \
                                            { "n": "state", "u": "boleean", "t": time.time(), "v": 1 }, \
                                            { "n": "init_hour", "u": "s", "t": time.time(), "v":self.manual_init_hour }, \
                                            { "n": "final_hour", "u": "s", "t": time.time(), "v":self.manual_final_hour }, \
                                            { "n": "current_intensity", "u": "percentage", "t": time.time(), "v":lamp["e"][0]["v"] }  \
                                            ]})


class run():

    def __init__(self, ThreadID, name,config):
        self.ThreadID = ThreadID
        self.shift = light_shift(config)
        self.shift.start_mqtt()
        self.alive = Iamalive(config)
        self.alive_interval = config["alive_interval"]


    def run(self):
        try:
            self.alive.start_mqtt()
            while True:
                self.alive.publish()  
                time.sleep(self.alive_interval)
        except KeyboardInterrupt:
                self.shift.stop()
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
                        [{ "n": "UV_light_shift", "u": "", "t": self.time, "v":"light_shift" }]}
    
    def start_mqtt(self):
        self.client.connect(self.broker,self.port)
        self.client.loop_start()

    def myconnect(self,paho_mqtt, userdata, flags, rc):
       print(f"Iamalive: Connected to {self.broker} with result code {rc} \n subtopic {self.sub_topic}, pubtopic {self.pub_topic}")

    def publish(self):
        self.message["e"][0]["t"]= time.time()
        __message=json.dumps(self.message)
        print(__message)
        print(self.pub_topic, self.broker, self.port)
        self.client.publish(topic=self.pub_topic,payload=__message,qos=2)

if __name__=="__main__":

    config = json.load(open("config_UV_light.json","r"))
    
    print("> Starting light shift...")
    main = run(3, "Mqtt",config)
    main.run()