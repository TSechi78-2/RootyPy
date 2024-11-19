import numpy
import time
import datetime    
import json
import paho.mqtt.client as pahoMQTT
import cherrypy
import requests
import threading
from requests.exceptions import HTTPError



class WaterTankAlert(object):

    def __init__(self,config_path,stop_event):
        config =  json.load(open(config_path,'r'))
        self.registry_url = config['url_registry']
        self.headers = config['headers']
        self.ID = config['ID']
        self.broker = config['broker']
        self.port = config['port']
        self.starting_time_tank = time.time()
        self.interval_tank = config['tank_interval']
        self.pub_topic = config['pub_topic']
        self.number_of_requests = config['number_of_requests']
        self.needed_urls = config['needed_urls']
        self.paho_mqtt = pahoMQTT.Client(self.ID,True)
        self.paho_mqtt.on_connect = self.myconnect_live
        self.stop_event = stop_event

        self.start_mqtt()

    def check_water_level(self):
        try:
            while True:
                r = self.get_response(self.registry_url+'/models')
                models = json.loads(r.text)
                r = self.get_response(self.registry_url+'/users')
                users = json.loads(r.text)
                userwithchatid = []
                for user in users:
                    if user['chatID'] != None:
                        userwithchatid.append(user['userId'])
                r = self.get_response(self.registry_url+'/plants')
                plants = json.loads(r.text)
                plantwithchatid = []
                for plant_diz in plants:
                    if plant_diz['userId'] in userwithchatid:    
                        plantwithchatid.append((plant_diz['plantCode'],plant_diz['userId']))
                for plant_u_tuple in plantwithchatid:
                    tank_level_series=  json.loads(requests.get(f'{self.needed_urls['adaptor']}/getData/{plant_u_tuple[1]}/{plant_u_tuple[0]}',params={"measurament":'tankLevel',"duration":1}).text)
                    if len(tank_level_series) > 0:
                        actual_tank_level = tank_level_series[-1]["v"]
                        curr_model = plant_u_tuple[0][:2]
                        for model in models:
                            if model['model_code'] == curr_model:
                                tank_capacity = model['tank_capacity']
                        tank_level_th = 0.1 * tank_capacity
                        if actual_tank_level < tank_level_th:
                            topic = self.pub_topic+f'/{plant_u_tuple[1]}/{plant_u_tuple[0]}'
                            message = {"bn": self.ID,"e":[{ "n": plant_diz['plantCode'], "u": "", "t": time.time(), "v":"alert" }]}
                            self.publish(topic,message)
                            print(f'sent {json.dumps(message)} at {topic}')
                    else:
                        pass
                time.sleep(self.interval_tank)
        except Exception as e:
            print('Water tank level stopped working')
            self.stop_event.set()

    def start_mqtt(self):
        print('>starting i am alive')
        self.paho_mqtt.connect(self.broker,self.port)
        self.paho_mqtt.loop_start()

    def myconnect_live(self,paho_mqtt, userdata, flags, rc):
       print(f"watertankalert: Connected to {self.broker} with result code {rc}")

    def publish(self,topic,message):
        __message=json.dumps(message)
        #print(f'message sent at {time.time()} to {self.pub_topic}')
        self.paho_mqtt.publish(topic,payload=__message,qos=2)

    def get_response(self,url):
        for i in range(self.number_of_requests):
            try:
                response = requests.get(url)
                response.raise_for_status()
                return response
            except HTTPError as http_err:
                print(f"HTTP error occurred: {http_err}")
            except Exception as err:
                print(f"Other error occurred: {err}")
        return None
    
    def get_needed_urls(self):
        return self.needed_urls
    
    def set_needed_urls(self,new_urls):
        self.needed_urls = new_urls
        
class Iamalive(object):
    #Object that takes care of sending periodics messages to the service registry 
    def __init__(self ,config_path,stop_event):

        json_config =  json.load(open(config_path,'r'))
        # mqtt attributes
        self.clientID = json_config["ID"]
        self.broker = json_config["broker"]
        self.port = json_config["port"]
        self.pub_topic = json_config["iamalive_topic"]
        self.paho_mqtt = pahoMQTT.Client(self.clientID,True)
        self.paho_mqtt.on_connect = self.myconnect_live
        self.message = {"bn": "updateCatalogService","e":[{ "n": f"{self.clientID}", "u": "", "t": time.time(), "v":"" }]} # Message that the registry is going to receive
        self.starting_time = time.time()      # this variable is gonna be updated to check and send the message
        self.interval = json_config["update_time"]
        self.url_registry = json_config["url_registry"]
        print('i am alive initialized')
        self.start_mqtt()
        self.stop_event = stop_event

    def ask_for_urls(self,needed_urls):

        while '' in needed_urls.values():

            services = json.loads(requests.get(self.url_registry+'/services').text)
            print(needed_urls)
            for service in services:
                if service['serviceID'] in needed_urls.keys():
                    needed_urls[service['serviceID']] = service['route'] 

        return needed_urls            

    def start_mqtt(self):
        print('>starting i am alive')
        self.paho_mqtt.connect(self.broker,self.port)
        self.paho_mqtt.loop_start()

    def myconnect_live(self,paho_mqtt, userdata, flags, rc):
       # Feedback on the connection
       print(f"Watertankalert: Connected to {self.broker} with result code {rc}")

    def check_and_publish(self):
        # Updates the time value of the message
        while  not self.stop_event.is_set():
            actual_time = time.time()
            if actual_time > self.starting_time + self.interval:
                self.publish()
                self.starting_time = actual_time
            time.sleep(15)

    def publish(self):
        # Publishes the mqtt message in the right format
        __message=json.dumps(self.message)
        print(f'message sent at {time.time()} to {self.pub_topic}')
        self.paho_mqtt.publish(topic=self.pub_topic,payload=__message,qos=2)

class ThreadManager:
    #Manages the creation and starting of threads for the report generator and the 
    #'I am alive' status checker.
    def __init__(self, watertankalert, iamalive):
        self.watertankalert = watertankalert
        self.iamalive = iamalive
        self.watertankalert.set_needed_urls(self.iamalive.ask_for_urls(self.watertankalert.get_needed_urls()))
    def start_threads(self):
        threading.Thread(target=self.watertankalert.check_water_level).start()
        threading.Thread(target=self.iamalive.check_and_publish).start()

if __name__ == '__main__':
    config_path = 'config_watertankalert.json'
    stop_event = threading.Event()
    report_generator = WaterTankAlert(config_path,stop_event)
    iamalive = Iamalive(config_path,stop_event)  # Provide the actual path to your config file

    # Start the threads
    thread_manager = ThreadManager(report_generator, iamalive)
    thread_manager.start_threads()
        