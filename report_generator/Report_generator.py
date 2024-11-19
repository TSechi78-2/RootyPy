import json
import requests
import time
import datetime
import paho.mqtt.client as pahoMQTT
import numpy as np
import matplotlib.pyplot as plt
from io import BytesIO
from PIL import Image
import base64
import threading
import cherrypy



class Report_generator(object):
            
    exposed = True

    def __init__(self,config_path,stop_event):
        config =  json.load(open(config_path,'r'))
        self.registry_url = config['url_registry']
        self.headers = config['headers']
        self.ID = config['ID']
        self.broker = config['broker']
        self.port = config['port']
        self.start_time = time.time()
        self.actual_time = time.time()
        self.target_hour = config['target_hour']
        self.target_minute = config['target_minute']
        self.time_zone_correction = config['time_zone_correction']
        self.needed_urls = config['needed_urls']
        self.stop_event = stop_event
        self.start_web_server( )

    def get_needed_urls(self):
        return self.needed_urls
    
    def set_needed_urls(self,new_urls):
        self.needed_urls = new_urls

    def start_web_server(self):


        conf={
            '/':{
            'request.dispatch':cherrypy.dispatch.MethodDispatcher(),
            'tools.sessions.on':True
            }
        }
        cherrypy.tree.mount(self,'/',conf)
        cherrypy.config.update({'server.socket_port': 8081})
        cherrypy.config.update({'server.socket_host':'0.0.0.0'})
        cherrypy.engine.start()
        print('report generator server exposed')
        
    def stop_server(self):
        pass


    def plot_data(self, timestamps, values, color,title,yax):
        """
        Plots the soil moisture values over time.

        :param timestamps: List of timestamps.
        :param moisture_values: List of soil moisture values.
        :param color: Color of the plot line.
        :return: BytesIO object containing the plot image.
        """
        plt.figure(figsize=(10, 6))
        plt.plot(timestamps, values, label=yax, marker='o', linestyle='-', color=color)
        plt.title(title)
        plt.xlabel('Time')
        plt.ylabel(yax)
        plt.legend()
        plt.grid(True)


        plt.xticks(rotation=45)

        plt.tight_layout()

        # Save the plot to a BytesIO object
        buffer = BytesIO()
        plt.savefig(buffer, format='png')
        buffer.seek(0)

        return buffer

        
    def concatenate_images_vertically(self, buffer1, buffer2, buffer3):
        """
        Concatenates four images vertically from BytesIO buffers and returns a new BytesIO buffer containing the combined image.
        
        :param buffer1: BytesIO object containing the first image.
        :param buffer2: BytesIO object containing the second image.
        :param buffer3: BytesIO object containing the third image.
        :return: BytesIO object containing the concatenated image.
        """
        # Load images from buffers
        image1 = Image.open(buffer1)
        image2 = Image.open(buffer2)
        image3 = Image.open(buffer3)

        
        # Get dimensions
        width1, height1 = image1.size
        width2, height2 = image2.size
        width3, height3 = image3.size

        
        # Create a new image with combined height
        total_height = height1 + height2 + height3
        max_width = max(width1, width2, width3)
        combined_image = Image.new('RGB', (max_width, total_height))
        
        # Paste images into the new image
        combined_image.paste(image1, (0, 0))
        combined_image.paste(image2, (0, height1))
        combined_image.paste(image3, (0, height1 + height2))

        
        # Save the combined image to a new BytesIO buffer
        combined_buffer = BytesIO()
        combined_image.save(combined_buffer, format='png')
        combined_buffer.seek(0)
        
        return combined_buffer


    def convert_timestamps(self,timestamps, duration):
        """
        Converts a list of timestamps from the format '%Y-%m-%d %H:%M:%S' into 
        '%m-%d' or '%m-%d-%H:%M:%S' based on the duration.

        Parameters:
        timestamps (list of str): List of timestamps in the format '%Y-%m-%d %H:%M:%S'.
        duration (int): The duration to determine the format of conversion.

        Returns:
        list of str: List of converted timestamps in the specified format.
        """
        converted_timestamps = []
        
        if duration > 6 * 24:
            # Convert to '%m-%d' format
            for ts in timestamps:
                dt = ts[:10]
                converted_timestamps.append(dt)
        else:
            # Convert to '%m-%d-%H:%M:%S' format
            for ts in timestamps:
                dt = ts[11:]
                converted_timestamps.append(dt)
        
        return converted_timestamps

    def on_connect(self, client, userdata, flags, rc):
        """
        Callback function for when the client receives a CONNACK response from the server.
        
        :param client: The client instance for this callback.
        :param userdata: The private user data as set in Client() or userdata_set().
        :param flags: Response flags sent by the broker.
        :param rc: The connection result.
        """
        if rc == 0:
            print("Connected to MQTT Broker successfully")
        else:
            print(f"Failed to connect, return code {rc}\n")


    def calculate_light_fluctuation(self,light_data):
        """
        Calculate the light fluctuation from the light data vector.
        Light fluctuation measures how much the light levels fluctuate throughout the day.
        """
        max_light = max(light_data)
        min_light = min(light_data)
        fluctuation = max_light - min_light
        return fluctuation

    def calculate_water_absorption(self,soil_moisture_data):
        """
        Calculate the water absorption rate from the soil moisture data.
        Water absorption rate indicates how quickly the plant uses the water administered.
        """
        if len(soil_moisture_data) >=2:
            derivative = []
            for i in range(len(soil_moisture_data)-2):

                initial_moisture = soil_moisture_data[i]
                final_moisture = soil_moisture_data[i+2]
                water_absorption = (initial_moisture - final_moisture)/3
                derivative.append(water_absorption)
            np.median(water_absorption)
            return water_absorption
        else:
            return 0

    def analyze_plant_conditions(self, DLI, light_fluctuation, soil_moisture_data, water_absorption):
        try:
            tips = []

            # Daily Light Integral (DLI) analysis
            if DLI < 35000:
                tips.append("Increase the amount of light your plant receives.")
            elif DLI > 60000:
                tips.append("Reduce the amount of light your plant receives.")

            # Light Fluctuation Analysis
            if light_fluctuation > 100:
                tips.append("Ensure more consistent lighting conditions for your plant.")

            flag_humidity = False
            # Check for narrow peaks in soil moisture
            peak_width_threshold = 20  # Threshold for narrow peaks
            for i in range(1, len(soil_moisture_data) - 1):
                if soil_moisture_data[i] > soil_moisture_data[i - 1] and soil_moisture_data[i] > soil_moisture_data[i + 1]:
                    peak_width = soil_moisture_data[i] - max(soil_moisture_data[i - 1], soil_moisture_data[i + 1])
                    if peak_width > peak_width_threshold:
                        flag_humidity = True
                        
            if flag_humidity:
                tips.append("Consider moving the plant to a more humid environment.")
            # Water Administration Efficiency
            if water_absorption < 0.5:
                tips.append("Check for root health or consider changing watering methods.")

            # Additional checks and tips
            if light_fluctuation < 200:
                tips.append("Check for potential shading or obstruction affecting light levels.")
            if max(soil_moisture_data) > 120:
                tips.append("Ensure proper drainage to prevent waterlogging and root rot.")
            if min(soil_moisture_data) < 10:
                tips.append("Water your plant more frequently to prevent dehydration.")
            if water_absorption > 9:
                tips.append("Monitor for signs of overwatering such as yellowing leaves or wilting.")
            if min(soil_moisture_data) > 80 and DLI < 20000:
                tips.append("During periods of low light and high soil moisture, reduce watering to avoid root suffocation.")
            if max(soil_moisture_data) < 20 and DLI > 40000:
                tips.append("In periods of high light and low soil moisture, increase watering to prevent wilting.")
            if DLI < 10000 and min(soil_moisture_data) > 40:
                tips.append("During periods of very low light and moderate soil moisture, increase the received light to prevent fungal diseases.")
            if light_fluctuation > 40000 and min(soil_moisture_data) > 50:
                tips.append("In cases of high light fluctuation and consistently high soil moisture, ensure proper ventilation to prevent mold growth.")

            if DLI > 40000 and water_absorption < 0.5:
                tips.append("In periods of high light and low water absorption, consider fertilizing to support plant growth.")
            if DLI < 10000 and water_absorption > 5:
                tips.append("During periods of low light and high water absorption, reduce fertilization to prevent nutrient buildup.")

            string_of_tips = ''                         #concatenates all the tips into a string
            for tip in tips:
                string_of_tips = string_of_tips + '\n' + tip

            return string_of_tips
        except Exception as e:
            print(f"Error analyzing plant conditions: {e}")

    def publish_image_via_mqtt(self, combined_buffer,message, mqtt_broker, mqtt_port, mqtt_topic):
        """
        Publishes an image and a message via MQTT.
        
        :param combined_buffer: BytesIO object containing the combined image.
        :param mqtt_broker: MQTT broker address.
        :param mqtt_port: MQTT broker port.
        :param mqtt_topic: MQTT topic to publish to.
        :param message: Message to include with the image.
        """
        client = pahoMQTT.Client()

        # Assign the on_connect callback function
        client.on_connect = self.on_connect

        client.connect(mqtt_broker, mqtt_port, 60)

        # Start the loop
        client.loop_start()

        # Convert image to base64 string
        combined_buffer.seek(0)
        image_base64 = base64.b64encode(combined_buffer.read()).decode('utf-8')

        # Create payload dictionary
        payload = {
            'bn': self.ID,"e":[{"n":'image',"u":"","t":time.time(),"v":image_base64},{"n":'message',"u":"","t":time.time(),"v":message}]
        }
        # Serialize payload to JSON
        payload_json = json.dumps(payload)

        # Publish the JSON string
        client.publish(mqtt_topic, payload_json, qos=2)
        
        # Stop the loop
        time.sleep(2)  # Wait for the message to be sent
        client.loop_stop()
        client.disconnect()

    def create_image(self,sunlight_timestamps, sunlight_values, lamp_timestamps, lamp_lux, moisture_timestamps, moisture_values):
        #Merges all the plot into a single one
        lux_plot = self.plot_data(sunlight_timestamps, sunlight_values,'yellow','Daily light interval','DLI')
        lamp_plot = self.plot_data(lamp_timestamps, lamp_lux,'violet','uv light emitted over time','lux')
        moisture_plot = self.plot_data(moisture_timestamps, moisture_values,'blue','moisture over time','moisture')
        combined_plot = self.concatenate_images_vertically(lux_plot,lamp_plot,moisture_plot)

        return combined_plot
                

    def send_daily_reports(self):
        # Asks for the plant with report frequency set to daily and sends the report
        try:
            plants = requests.get(self.registry_url + '/plants')
            plants = json.loads(plants.text)
            print(f'GET request sent at {self.registry_url}/plants')
        except Exception as e:
            print(f'Error fetching plants: {e}')

        for plant in plants:
            if plant['report_frequency'] == 'daily':
                user = plant['userId']
                chatID = self.get_chatID_from_user(user)
                if chatID is None:
                    continue
                self.generate_report(user, plant['plantCode'], duration=24)

    def send_weekly_reports(self):
        # Asks for the plant with report frequency set to weekly and sends the report
        try:
            plants = requests.get(self.registry_url + '/plants')
            plants = json.loads(plants.text)
            print(f'GET request sent at {self.registry_url}/plants')
        except Exception as e:
            print(f'Error fetching plants: {e}')


        for plant in plants:
            if plant['report_frequency'] == 'weekly':
                user = plant['userId']
                chatID = self.get_chatID_from_user(user)
                if chatID is None:
                    continue
                if plant['report_frequency'] == 'weekly':
                    self.generate_report(user, plant['plantCode'], duration=7*24)

    def send_biweekly_reports(self):
        # Asks for the plant with report frequency set to biweekly and sends the report
        try:
            plants = requests.get(self.registry_url + '/plants')
            plants = json.loads(plants.text)
            print(f'GET request sent at {self.registry_url}/plants')
        except Exception as e:
            print(f'Error fetching plants: {e}')

            for plant in plants:
                if plant['report_frequency'] == 'biweekly':
                    user = plant['userId']
                    chatID = self.get_chatID_from_user(user)
                    if chatID is None:
                        continue
                    if plant['report_frequency'] == 'biweekly':
                        self.generate_report(user, plant['plantCode'], duration=14*24)

    def send_monthly_reports(self):
        # Asks for the plant with report frequency set to monthly and sends the report
        try:
            plants = requests.get(self.registry_url + '/plants')
            plants = json.loads(plants.text)
            print(f'GET request sent at {self.registry_url}/plants')
        except Exception as e:
            print(f'Error fetching plants: {e}')

            for plant in plants:
                if plant['report_frequency'] == 'monthly':
                    user = plant['userId']
                    chatID = self.get_chatID_from_user(user)
                    if chatID is None:
                        continue
                    if plant['report_frequency'] == 'monthly':
                        self.generate_report(user, plant['plantCode'], duration=30*24)

    def schedule_and_send_messages(self):
        """
        Continuously checks the current time and sends scheduled reports.

        This method runs an infinite loop where it checks the current time against the
        start_time every 60 seconds. Depending on the corrected current time, it sends
        daily, weekly, bi-weekly, or monthly reports at specified times.
        """
        while True:
            # Get the current date and time
            now = datetime.datetime.now()
            print(now)
            # Adjust the current hour based on the time zone correction
            time_zone_corrected_now = now.hour - self.time_zone_correction
            
            # Correct the hour if it exceeds 24 or is below 0
            if time_zone_corrected_now > 24:
                time_zone_corrected_now -= 24
            elif time_zone_corrected_now < 0:
                time_zone_corrected_now = 24 + time_zone_corrected_now
            
            # Check if the current time matches the scheduled report time
            if now.hour + self.time_zone_correction == self.target_hour and now.minute == self.target_minute:
                # Send daily reports
                self.send_daily_reports()
                
                # If today is Sunday, send weekly reports
                if now.weekday() == 6:  # Sunday
                    self.send_weekly_reports()
                
                # Send bi-weekly reports on the 14th and 28th of each month
                if now.day == 14 or now.day == 28:
                    self.send_biweekly_reports()
                
                # Send monthly reports on the 15th of each month
                if now.day == 15:
                    self.send_monthly_reports()
            time.sleep(60)

    def generate_report(self, user, plant, duration=24, instant=False):
        """
        Generates and optionally sends a report for a specific plant.

        This method collects sensor data for the specified duration, generates an image
        summarizing the data, and provides tips based on the plant's conditions. The report
        can either be published via MQTT or returned immediately.

        Parameters:
            user (str): The username associated with the plant.
            plant (str): The plant code.
            duration (int): The duration for which data is collected, in hours. Default is 24.
            instant (bool): If True, the report is returned immediately. If False, it is published via MQTT.
        """
        # Fetch DLI (Daily Light Integral) data for the specified duration
        lux_sensor = json.loads(requests.get(f'{self.needed_urls['adaptor']}/getData/{user}/{plant}', params={"measurament": 'DLI', "duration": duration}).text)
        
        # Fetch current light intensity data for the specified duration
        lux_emitted = json.loads(requests.get(f'{self.needed_urls['adaptor']}/getData/{user}/{plant}', params={"measurament": 'current_intensity', "duration": duration}).text)
        
        # Extract timestamps and values for emitted light
        lux_emitted_timestamps = [datapoint['t'] for datapoint in lux_emitted]
        lux_emitted_values = [datapoint['v'] for datapoint in lux_emitted]
        
        # Extract timestamps and values for sunlight
        lux_sunlight_timestamps = [datapoint['t'] for datapoint in lux_sensor]
        lux_sunlight_values = [datapoint['v'] for datapoint in lux_sensor]
        
        # Fetch moisture data for the specified duration
        moisture = json.loads(requests.get(f'{self.needed_urls['adaptor']}/getData/{user}/{plant}', params={"measurament": 'moisture', "duration": duration}).text)
        
        # Extract timestamps and values for moisture
        moisture_timestamps = [datapoint['t'] for datapoint in moisture]
        moisture_values = [datapoint['v'] for datapoint in moisture]
        
        # Fetch plant model information
        r = requests.get(self.registry_url + '/models')
        models = json.loads(r.text)
        
        # Find the maximum lamp capacity for the plant model
        for model in models:
            if model['model_code'] == plant[:2]:
                lamp_capacity = model['max_lux']
        
        # Adjust emitted light values based on lamp capacity
        lux_emitted_values = [value * lamp_capacity for value in lux_emitted_values]
        
        # Convert timestamps to a readable format
        lux_sunlight_timestamps = self.convert_timestamps(lux_sunlight_timestamps, duration)
        lux_emitted_timestamps = self.convert_timestamps(lux_emitted_timestamps, duration)
        moisture_timestamps = self.convert_timestamps(moisture_timestamps, duration)
        
        # Generate a combined image from the collected data
        combined_image = self.create_image(lux_sunlight_timestamps, lux_sunlight_values, lux_emitted_timestamps, lux_emitted_values, moisture_timestamps, moisture_values)
        
        # Calculate Daily Light Integral (DLI)
        dli = lux_sunlight_values[-1]
        
        # Calculate light fluctuation
        light_fluctuation = self.calculate_light_fluctuation(lux_sunlight_values)
        
        # Calculate water absorption
        water_absorption = self.calculate_water_absorption(moisture_values)
        
        # Analyze plant conditions and generate tips
        tips = self.analyze_plant_conditions(dli, light_fluctuation, moisture_values, water_absorption)
        
        if not instant:
            # Publish the image and tips via MQTT
            self.publish_image_via_mqtt(combined_image, tips, self.broker, self.port, f'RootyPy/report_generator/{user}/{plant}')
        else:
            # Prepare the image for immediate sending
            combined_image.seek(0)
            image_base64 = base64.b64encode(combined_image.read()).decode('utf-8')
            
            # Create payload dictionary
            body = {'bn': self.ID,'e':[{'n': 'image','u':'bytes','t':time.time(),'v': image_base64},{'n':'message','u':'text','t':time.time(),'v':tips}]
            }
            
            # Print message for debugging
            print(f"Message sent to {user} for plant {plant} with instant: {instant}")
            
            # Return the payload
            return body


    def get_chatID_from_user(self,user):
            # With a GET request to the registry search for the userid associated to a certain user
            r = requests.get(self.registry_url+'/users',headers = self.headers)
            print(f'GET request sent at \'{self.registry_url}/users')
            output = json.loads(r.text)
            for diz in output:
                if diz['userId'] == user:
                    if diz['chatID'] != None:
                        chatID =diz['chatID']
                        return chatID
                    else:
                        return None


    def GET(self,*uri,**params):
        print(f'get request received at {uri}')
        if uri[0] == 'getreport':
            r = requests.get(self.registry_url+'/plants',headers=self.headers)
            output = json.loads(r.text)
            found = False
            for diz in output:
                if diz['plantCode'] == uri[1]:
                    found = True
                    userid = diz['userId']
                    plantname = diz['plantCode']
                    body =self.generate_report(userid,plantname,instant =True)
            if not found:   
                response = {"status": "NOT_OK", "code": 400, "message": "Invalid user"}
            else:
                response = body
            return json.dumps(response) 
        
    def POST(self,*uri,**params):
        pass

    def PUT(self,*uri,**params):
        pass    

    def DELETE(self,*uri,**params):
        pass


class Iamalive(object):
    #Object that takes care of sending periodics messages to the service registry 
    def __init__(self ,config_path,stop_event):

        json_config =  json.load(open(config_path,'r'))
        # mqtt attributes
        self.clientID = json_config["ID"]
        self.broker = json_config["broker"]
        self.port = json_config["port"]
        self.pub_topic = json_config["alive_topic"]
        self.paho_mqtt = pahoMQTT.Client(self.clientID,True)
        self.paho_mqtt.on_connect = self.myconnect_live
        self.message = {"bn": "updateCatalogService","e":[{ "n": f"{self.clientID}", "u": "IP", "t": time.time(), "v":json_config['myurl'] }]} # Message that the registry is going to receive
        self.starting_time = time.time()          # this variable is gonna be updated to check and send the message
        self.interval = json_config["update_time"]
        self.url_registry = json_config["url_registry"]
        self.stop_event = stop_event
        self.start_mqtt()  

    def ask_for_urls(self,needed_urls):

        while '' in needed_urls.values():

            services = json.loads(requests.get(self.url_registry+'/services').text)
            print(needed_urls)
            for service in services:
                if service['serviceID'] in needed_urls.keys():
                    needed_urls[service['serviceID']] = service['route'] 

        return needed_urls     

    def start_mqtt(self):
        # Connects to broker and starts the mqtt
        print('>starting i am alive')
        self.paho_mqtt.connect(self.broker,self.port)
        self.paho_mqtt.loop_start()

    def myconnect_live(self,paho_mqtt, userdata, flags, rc):
       # Feedback on the connection
       print(f"Report generator: Connected to {self.broker} with result code {rc}")

    def check_and_publish(self):
        # Updates the time value of the message
        while  not self.stop_event.is_set():
            self.publish()
            time.sleep(self.interval)

    def publish(self):
        # Publishes the mqtt message in the right fromat
        __message=json.dumps(self.message)
        print(f'message sent at {time.time()} to {self.pub_topic}')
        self.paho_mqtt.publish(topic=self.pub_topic,payload=__message,qos=2)

class ThreadManager:
    #Manages the creation and starting of threads for the report generator and the 
    #'I am alive' status checker.
    def __init__(self, reportgenerator, iamalive):
        self.reportgenerator = reportgenerator
        self.iamalive = iamalive
        self.reportgenerator.set_needed_urls(self.iamalive.ask_for_urls(self.reportgenerator.get_needed_urls()))

    def start_threads(self):
        threading.Thread(target=self.reportgenerator.schedule_and_send_messages).start()
        threading.Thread(target=self.iamalive.check_and_publish).start()

if __name__ == '__main__':
    config_path = 'config_report_generator.json'
    stop_event = threading.Event()
    report_generator = Report_generator(config_path,stop_event)
    iamalive = Iamalive(config_path,stop_event)  # Provide the actual path to your config file

    # Start the threads
    thread_manager = ThreadManager(report_generator, iamalive)
    thread_manager.start_threads()
