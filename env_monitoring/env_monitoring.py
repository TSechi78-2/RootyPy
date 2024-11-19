import paho.mqtt.client as PahoMQTT
import time
import json
import numpy as np
import requests as req
from datetime import datetime,timedelta
from requests.exceptions import HTTPError

class EnvMonitoring(object):
    def __init__(self,settings):
        #load settings
        self.base_topic=settings['basetopic']
        self.port=settings['port']
        self.broker=settings['broker']
        self.clientID=settings['ID']
        self.default_time=settings['default_time']
        self.alive_topic=f"{self.base_topic}/{self.clientID}_alive" #RootyPy/Env_monitoring_alive
        self.url_registry=settings['url_registry']

        #Variables to activate simulation
        self.simMode=settings['simMode'] 
        self.startedSim=0
        #####
        
        self._paho_mqtt=PahoMQTT.Client(self.clientID, True) #Client definition
        self._paho_mqtt.on_connect=self.MyOnConnect
        self.__message={"bn":"", 'e':[{'n':'light_deficit','u':"lux",'t':'','v':None } #message sent to UV_light_shift
                                                 ]}
        self.dli_rec_message={"bn":"", 'e':[{'n':'DLI','u':"DLI",'t':'','v':None } #message sent to adaptor
                                                 ]}
        

    def start(self):
        self._paho_mqtt.connect(self.broker,self.port)
        self._paho_mqtt.loop_start()

    def stop(self):
        self._paho_mqtt.loop_stop()
        self._paho_mqtt.disconnect()

    def MyOnConnect(self,paho_mqtt,userdata,flags,rc):
        print(f"EnvMonitoring: Connected to {self.broker} with result code {rc}")
    
    def MyPublish(self):
        #requesting info needed from registry
        plants,url_adptor,models,valid_plant_types=self.RequestsToRegistry()
        if self.simMode==1:
            if self.startedSim>=24:
                self.startedSim=0
            else:
                self.startedSim+=1
        #for each plant in registry
        for plant in plants:
                
            plant_type=plant['type']        #Category of the plant
            userId=plant['userId']          #User assigned to the the plant
            plant_code=plant["plantCode"]   #Unique code of the vase

            #From the code, retrive maximum lux value that that specific vase lamp can give
            max_lux_lamp=self.retriveMaxLuxLamp(plant_code,models)

            start_time=plant['auto_init']   #User defined time to start Automatic lamp adjustment
            end_time=plant['auto_end']      #User defined time to end Automatic lamp adjustment
            
            #discriminatoir between auto and sim mode
            
            if self.simMode==0: #simMode off
                current_time = datetime.now().time() #use current real time
                current_datetime = datetime.combine(datetime.today(), current_time) 
                start_datetime = datetime.combine(datetime.today(),datetime.strptime(start_time, '%H:%M').time()) #transform string to time
                time_difference = current_datetime - start_datetime #define time difference
                
                hours_passed = round(time_difference.total_seconds() / 3600) #find how many hour are passed

                #if result is negative, adjust
                if hours_passed <0:
                    hours_passed=24+hours_passed
                else:
                    #if 0, take 1 (can't request 0 to adaptor)
                    hours_passed=max(hours_passed,1)

                end_datetime = datetime.combine(datetime.today(), datetime.strptime(end_time, '%H:%M').time()) #transform time string to time
                time_difference = end_datetime - start_datetime #hors difference between them
                suncycle = round(time_difference.total_seconds() / 3600) #is the periodt defined by the user at wich the auto mode is activated
            
            else:
                #If sim mode is on, hour count is incremented each minute : 1m=1h
                
                print("simMode started")
                #from midnight of today
                current_datetime = datetime.combine(datetime.today(),datetime.strptime("00:00", '%H:%M').time())
                #add time difference
                current_datetime += timedelta(hours=self.startedSim)
                print(current_datetime)
                start_datetime = datetime.combine(datetime.today(),datetime.strptime(start_time, '%H:%M').time())
                time_difference = current_datetime - start_datetime
                hours_passed = round(time_difference.total_seconds() / 3600)

                if hours_passed <0:
                    hours_passed=24+hours_passed
                else:
                    #if 0, take 1 (can't request 0 to adaptor)
                    hours_passed=max(hours_passed,1)

                end_datetime = datetime.combine(datetime.today(), datetime.strptime(end_time, '%H:%M').time())
                time_difference = end_datetime - start_datetime
                suncycle = round(time_difference.total_seconds() / 3600)
            ###########
            #deficit estimation and DLi calculation
            lux_to_add,dli_recived_past_hour=self.PlantLuxEstimation(url_adptor,plant_code,plant_type,userId,hours_passed,suncycle,max_lux_lamp,valid_plant_types)
            current_msg=self.__message.copy()

            #define topic to send to uv_light shift
            current_topic=f"{self.base_topic}/{userId}/{plant_code}/lux_to_give/automatic"

            #prepare message to Uv_light_shift
            current_msg['e'][0]['t']=time.time()
            current_msg['e'][0]['v']=lux_to_add
            current_msg['bn']=current_topic

            #define topic to send to adaptor
            topicDLI=f"{self.base_topic}/{userId}/{plant_code}/DLI"
            dli_mess=self.dli_rec_message.copy()

            #prepare message to adaptor
            dli_mess['e'][0]['t']=time.time()
            dli_mess['e'][0]['v']=dli_recived_past_hour
            dli_mess['bn']=topicDLI
            dli_mess=json.dumps(dli_mess)

            #publish message to adaptor
            self._paho_mqtt.publish(topic=topicDLI,payload=dli_mess,qos=2)
            print(dli_mess)

            #check if time is over defined auto regolation period
            if current_datetime>=start_datetime and current_datetime<=end_datetime:
                __message=json.dumps(current_msg)
                print(__message)
                self._paho_mqtt.publish(topic=current_topic,payload=__message,qos=2)
            else:
                #if not publish 0 as lux to give
                current_msg['e'][0]['v']=0
                __message=json.dumps(current_msg)
                self._paho_mqtt.publish(topic=current_topic,payload=__message,qos=2)                 
        return

    

    def PublishAlive(self):
        '''
        This function publish the alive message to Registry to tell them that service is working.
        This is sent every 15 second.
        '''
        message={"bn":"updateCatalogService","e":[{"n": self.clientID, "t": time.time(), "v":None,"u":"IP"}]}
        __message=json.dumps(message)
        
        print(__message)
        self._paho_mqtt.publish(topic=self.alive_topic,payload=__message,qos=2)



    def get_response(self,url):
        
        for i in range(15):
            try:
                response = req.get(url)
                response.raise_for_status()
                return json.loads(response.text)
            except HTTPError as http_err:
                print(f"HTTP error occurred: {http_err}")
            except Exception as err:
                print(f"Other error occurred: {err}")
            # time.sleep(1)
        return []


    def RequestsToRegistry(self):        
        '''
        Request are needed info from the Registry
        returns: all plant registerd, the models, the types of plant and the adaptor url
        
        '''
        plants=self.get_response(f"{self.url_registry}/plants")
        models=self.get_response(f"{self.url_registry}/models")
        valid_plant_types=self.get_response(f"{self.url_registry}/valid_plant_types")
        active_services=self.get_response(f"{self.url_registry}/services")
        # response=req.get(f"{self.url_registry}/plants") #plant request        
        #find if adaptor is online
        for service in active_services:
            if service['serviceID']=="adaptor":
                url_adaptor=service['route']
                break
        # url_adaptor=self.url_adaptor

        return plants,url_adaptor,models,valid_plant_types
        
    def retriveMaxLuxLamp(self,plant_code,models):
        '''
        Function that retrive the max lux that the lamp in the current vase can give
        input: the code of the vase, the possible models
        returns: the max lux that can be given
        '''
        vase_type=plant_code[:2] #the type of vase is defined by the first 2 carachters of code
        for model in models:
            if model['model_code']==vase_type:
                max_lux_lamp=model["max_lux"]
                break
        return max_lux_lamp

    def PlantLuxEstimation(self,url_adptor,plant_code,plant_type,userId,hours_passed,suncycle,max_lux_lamp,valid_plant_types):               
        """Retrives all data needed for deficit calculation for a single plant
        """
        #Make reqest to adaptor for data needed
        mesurements_past_hour,DLI_daily_record,lamp_intensity_past_hour=self.PlantSpecificGetReq(url_adptor,userId,plant_code,hours_passed)
        #estimate lux given in prec hour, the lampintensity and all dli given till now
        lux_past_hour,mean_lamp_intensity,dli_given_today=self.LuxPastHour(mesurements_past_hour,lamp_intensity_past_hour,DLI_daily_record) 
        #retrive goal of plant based on type 
        current_plant_goal=self.PlantGoal(plant_type,valid_plant_types)
        #Do lux deficit calc
        lux_to_add,dli_recived_past_hour=self.LuxDeficitCalculation(current_plant_goal,suncycle,lux_past_hour,mean_lamp_intensity,dli_given_today,hours_passed,max_lux_lamp)
    
        return lux_to_add,dli_recived_past_hour

    def PlantSpecificGetReq(self,url_adaptor,userId,plant_code,hours_passed):
        ''' 
        All requests to the adaptor for informations plant specific
        input: url of the adaptor, the user id (plant owner), the specifc code of the vase, the time passed from the start time of auto mode
        returns: light mesurements in past hour, the intensity percentege of the lamp in past hour, All DLI records from start of auto mode 
        '''
        mesurements_past_hour=self.get_response(f"{url_adaptor}/getData/{userId}/{plant_code}?measurament=light&duration=1")
        # mesurements_past_hour=json.loads(req.get(f"{url_adaptor}/getData/{userId}/{plant_code}?measurament=light&duration=1").text)
        lamp_intensity_past_hour=self.get_response(f"{url_adaptor}/getData/{userId}/{plant_code}?measurament=current_intensity&duration=1")
        # lamp_intensity_past_hour=json.loads(req.get(f"{url_adaptor}/getData/{userId}/{plant_code}?measurament=current_intensity&duration=1").text)
        print(hours_passed)
        DLI_daily_record=self.get_response(f"{url_adaptor}/getData/{userId}/{plant_code}?measurament=DLI&duration={hours_passed}")
        # DLI_daily_record=json.loads(req.get(f"{url_adaptor}/getData/{userId}/{plant_code}?measurament=DLI&duration={hours_passed}").text)
        return mesurements_past_hour,DLI_daily_record,lamp_intensity_past_hour

    def LuxPastHour(self,mesurments_past_hour,lamp_intensity_past_hour,DLI_daily_record):
        '''
        Calculate the mean of the lux and the intensity at wich the plant was esposed and the total dli recived today
        inputs: all mesurement of lux and perc of intensity of lamp in past hour, all mesurements of DLI today
        #returns: mean of lux past hour, mean of intensity past hour, total DLI recived today
        '''
        lux_past_hour_v=[]
        lamp_past_hour_v=[]
        dli_given_today=float(0)
        if len(mesurments_past_hour)>0:
            for mesure in mesurments_past_hour:
                lux_past_hour_v.append(mesure['v'])
            lux_past_hour=np.mean(lux_past_hour_v)
        else:
            lux_past_hour=0

        if len(lamp_intensity_past_hour)>0:
            for intensity in lamp_intensity_past_hour:
                lamp_past_hour_v.append(intensity['v'])
            mean_light_intensity=np.mean(lamp_past_hour_v)
        else:
            mean_light_intensity=0

        if len(DLI_daily_record)>0:

            for dli in DLI_daily_record:
                dli_given_today=dli_given_today+dli['v']

        return lux_past_hour,mean_light_intensity,dli_given_today
    
    def PlantGoal(self,plant_type,valid_plant_types):

        '''
        Get the DLI goal for the current plant
        inputs: current plant type and all possible plant types
        returns: DLI goal for the current plant
        '''
        for ptype in valid_plant_types:

            if plant_type in ptype['type']:
                current_plant_goal=ptype['DLI_goal']

        return current_plant_goal
    
  
    def LuxDeficitCalculation(self,DLI_goal,sun_cycle,registered_Lux_hour,mean_lamp_intensity,dli_given_today,hours_passed,max_lux_lamp):
        '''
        Core of the microservice: 
        - Estimates Photosynthetic Photon Flux Density (PPFD) of lamp from the mean intensity of the lamp in past hour
        - Estimates PPFD of the sun by subtractiong the estimated LUX coming from the lamp from themean of lux recived in past hour
        - Sum the PPFD total and calculates the Daily Light Integral in past hour
        - From The DLI goal of the plants estimate how many DLI should be given per hour to reach goal based on the distance between start and end time
        - Update DLI goal for the current hour
        - Estimate lux deficit if the plant is the dli recived are less than the goal

        inputs: DLI goal for the current plant, the hours at wich the auto function is activated, the mean LUX recived in past hour, the mean lamp intensity,
                Dli given today, how many hours are passed form start of auto mode, maximum of lux that lamp can give
        outputs: The lux deficit to compensate, the DlI that were recived in past hour
        
        '''
        PPFDlamp=max_lux_lamp*(mean_lamp_intensity/100)*0.0135 #the factor depends on kind of lamp
        print(f'PPFDlamp:{PPFDlamp}')
        PPFDsun=(registered_Lux_hour-(max_lux_lamp*mean_lamp_intensity/100))*0.0185 #factor if the sun
        print(f"PPFDsun: {PPFDsun}")
        PPFDtot=PPFDsun+PPFDlamp
        DLIsun_hour=PPFDsun*0.0036
        DLIrecived_hour=max(float(0),PPFDtot*0.0036)
        print(f"DLIrecived_hour: {DLIrecived_hour}")
        dli_given_today+=DLIrecived_hour
        print(f"Dli given today: {dli_given_today}" )       
        DLIhgoal=DLI_goal/sun_cycle
        DLI_current_goal=min(DLI_goal,DLIhgoal*hours_passed) #cannot evaluate proprely because the hours passed does not grow enough rapidly
        print(f"DLI_current_goal: {DLI_current_goal}")
        if dli_given_today<DLI_current_goal:
            DLI_toAdd=DLI_current_goal-dli_given_today
            Lux_toAdd=DLI_toAdd/(0.0135*0.0036)
        else:
            Lux_toAdd = 0

        # Lux_recived=DLIrecived_hour/
        return Lux_toAdd,DLIrecived_hour
    
###################################################################################################################################################


def main():
    #load settings file
    settings=json.load(open("configEnv.json",'r'))
    #istance class
    function = EnvMonitoring(settings)
    #start mqtt
    function.start()
    #initialize reference time
    _time=time.time()

    while True: 
        #time passed from reference       
        time_passed=time.time()-_time
        print(f"time_passed: {time_passed}" )

        #chechs if time passed is more than the interval in settings
        if round(time_passed)>=settings['publishInterval']:
            function.MyPublish()
            function.PublishAlive()
            _time=time.time()       
                
        else:
            function.PublishAlive()
        time.sleep(15) 

if __name__ == "__main__":
    main()
 

