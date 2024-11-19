import cherrypy
import paho.mqtt.client as PahoMQTT
import cherrypy
import time
import json
import numpy as np
import requests as req
import threading
from datetime import datetime
from requests.exceptions import HTTPError


class MoistureMonitoring(object):
    def __init__(self,settings):
        #load settings
        self.base_topic=settings['pub_topic_moisturemonitoring']
        self.alive_topic = settings['pub_topic_Iamalive']
        self.port=settings['port']
        self.broker=settings['broker']
        self.clientID=settings['ID_moistureMonitoring']
        self.url_registry=settings['url_registry']


        ###############################################à

        
        self._paho_mqtt=PahoMQTT.Client(self.clientID, True)
        self._paho_mqtt.on_connect=self.MyOnConnect
        self.__message={"bn":"", 'e':[{'n':'water_deficit','unit':"percent",'t':'','v':None }]}

        

    def start(self):
        # Connect to MQTT broker and start the MQTT loop
        self._paho_mqtt.connect(self.broker,self.port)
        self._paho_mqtt.loop_start()

    def stop(self):
        # Stop the MQTT loop and disconnect from the broker
        self._paho_mqtt.loop_stop()
        self._paho_mqtt.disconnect()

    def MyOnConnect(self,paho_mqtt,userdata,flags,rc):
        # Callback function when connected to MQTT broker
        print(f"MoistureMonitoring: Connected to {self.broker} with result code {rc} \n subtopic {None}, pubtopic PROVA")

    def get_response(self,url):
        """
        Sends a GET request to the specified URL and returns the response.
        It tries 15 times to get the response, if it fails it returns an empty list.

        Args:
            url (str): The URL to send the GET request to.
        """
        for i in range(15):
            try:
                response = req.get(url)
                response.raise_for_status()
                return json.loads(response.text)
            except HTTPError as http_err:
                print(f"HTTP error occurred: {http_err}")
            except Exception as err:
                print(f"Other error occurred: {err}")
            time.sleep(1)
        return []

    def MyPublish(self, type):
        '''
        if function is passed as argument, the function will calculate the amount of water to give to each plant and publish it
        if alive is passed as argument, the function will publish an alive message
        '''

        if type == "function":
            plants,url_adptor,models=self.RequestsToRegistry() 
            
            for plant in plants:
                    
                    plant_type=plant['type']
                    plantId=plant['plantId']
                    userId=plant['userId']
                    plant_code=plant["plantCode"]
                    

                    jar_volume=self.retriveJarVolume(plant_code,models)
                    

                    water_to_add = self.PlantWaterEstimation(url_adptor,plant_code,plant_type,userId,jar_volume)

                    current_msg=self.__message.copy()
                    
                    current_topic=f"{self.base_topic}/{userId}/{plant_code}/water_to_give/automatic"

                    current_msg['e'][0]['t']=time.time()
                    current_msg['e'][0]['v']=water_to_add
                    current_msg['bn']=current_topic
                    


                    __message=json.dumps(current_msg)
                    print(__message)
                    print(current_topic)
                    self._paho_mqtt.publish(topic=current_topic,payload=__message,qos=2)
            print("\n\n\n")          

            return 
        else:
            message = {"bn":"updateCatalogService","e":[{"n":"MoistureMonitoring", "t": time.time(), "v":None,"u":"IP"}]}
            self._paho_mqtt.publish(topic=self.alive_topic,payload=json.dumps(message),qos=2)

    
    def RequestsToRegistry(self):        
            '''
            Request are needed info from the Registry
            returns: all plant registerd, the models and the adaptor url
            
            '''
            plants=self.get_response(f"{self.url_registry}/plants")
            models=self.get_response(f"{self.url_registry}/models")
            active_services=self.get_response(f"{self.url_registry}/services")
            #find if adaptor is online
            for service in active_services:
                if service['serviceID']=="adaptor":
                    url_adaptor=service['route']
                    break

            return plants,url_adaptor,models
    
    def retriveJarVolume(self,plant_code,models):
        '''
        returns the jar volume of the plant
        '''
        # Retrieve the jar volume based on the plant code

        vase_type=plant_code[:2]
        for model in models:
            if model['model_code']==vase_type:
                jar_volume=model["jar_volume"]
                break
        return jar_volume

    def PlantWaterEstimation(self,url_adptor,plant_code,plant_type,userId,jar_volume): 
        '''
        Estimate the amount of water to add to the plant based on the moisture goals and past measurements
        Args:
            plant_code (str): The plant code.
            plant_type (str): The plant type.
            userId (str): The user ID.
            jar_volume (float): The jar volume.
        The water is calculated as follows:
        1. Get the moisture goals for the plant type.
        2. Get the measurements of the past hour.
        3. Calculate the mean moisture of the past hour.
        4. If the mean moisture is less than the moisture goals, calculate the amount of water to add.
        5. Return the amount of water to add.
        '''
        valid_plants_types= self.get_response(f"{self.url_registry}/valid_plant_types")


        for plant in valid_plants_types:
            if plant_type == plant["type"]:
                moisture_goals=float(plant["moisture_goal"])
                print(f"Moisture goals for {plant_type}: {moisture_goals}")
                break
        mesurements_past_hour=self.PlantSpecificGetReq(url_adptor,userId,plant_code,moisture_goals)
        mesurements_past_hour_moisture = []
        for mesure in mesurements_past_hour:
                mesurements_past_hour_moisture.append(mesure['v'])
        mean_moisture_past_hour= np.mean(mesurements_past_hour_moisture)
        # mean_moisture_past_hour = float(mesurements_past_hour_moisture[-1])


        if moisture_goals - mean_moisture_past_hour > 0:
            water_to_add = (moisture_goals - mean_moisture_past_hour)/100 * jar_volume
        else:
            water_to_add = 0
    
        return water_to_add

    def PlantSpecificGetReq(self,url_adaptor,userId,plant_code,moisture_goals):
    # Send HTTP GET request to the adaptor to get plant-specific data about the optimal moisture level
        mesurements_past_hour=self.get_response(f"{url_adaptor}/getData/{userId}/{plant_code}?measurament=moisture&duration=1")
        

        if len(mesurements_past_hour)==0:
            mesurements_past_hour = [{"t": f"{datetime.now()}, {time.time()}", "v": moisture_goals + 1}]
            return mesurements_past_hour
        else: 
            return mesurements_past_hour

class run(object): 
    def __init__(self,settings):
        
        
        self.function = MoistureMonitoring(settings)
        self.function.start()
        self.update_time=float(settings['update_time'])
        self.alive_interval = settings['alive_interval']
        
    def run(self):
        '''
        this function run publish every update_time the amount of water to give to each plant and every alive_interval an alive message
        '''
        
        try:
            start = time.time()
            while True:
                    ##################################################################
                    if time.time()-start > self.update_time: 
                    ##################################################################
                        self.function.MyPublish("function")
                        start = time.time()
                    self.function.MyPublish("alive")     
                    time.sleep(self.alive_interval)

                
        except KeyboardInterrupt:
                self.function.stop()


if __name__ == "__main__":

    time.sleep(5)
    settings=json.load(open("configWat.json",'r'))
    tFunction = run(settings)
    print("> Starting moisture monitoring function...")
    tFunction.run()


