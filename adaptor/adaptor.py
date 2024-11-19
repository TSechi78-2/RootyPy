from datetime import datetime
from influxdb_client import InfluxDBClient, Point, WritePrecision, BucketRetentionRules
from influxdb_client.client.write_api import SYNCHRONOUS
import json
import cherrypy
import paho.mqtt.client as PahoMQTT
import time
import threading
from pathlib import Path
import requests
from requests.exceptions import HTTPError

P = Path(__file__).parent.absolute()
SETTINGS = P / "settings.json"

def get_request(url):
    """Function to try multiple requests if errors are encountered"""
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

def senmlToInflux(senml, plantId):
    """Change data format from senML to influxDB standard"""
    output = []   
    for e in senml["e"]:
        point = {
        "measurement":"",
        "tags":"",
        "fields": ""
        }
        point["measurement"] = plantId
        point["tags"] = {"unit": e["u"]}
        point["fields"] = {e["n"]:e["v"]}
        output.append(point)
    return output  

class Adaptor(object):
    """WebServer for the adaptor"""
    exposed=True
    def __init__(self):
        with open(SETTINGS, 'r') as file:
                settings = json.load(file)
        self.token = settings["influx_token"]
        self.org = settings["influx_org"]
        self.url = settings["adaptor_url"]
        self.influxUrl = settings["url_db"]
        self.registryBaseUrl = settings["registry_url"]
        self.possServices = settings["services4db"]
        self.port = settings["adaptor_port"]
        self.client = InfluxDBClient(url=self.influxUrl, token=self.token)
        self.bucket_api = self.client.buckets_api()
        self.test = settings["test"]
        self.loadUsers()
        
    def loadUsers(self):
        url = self.registryBaseUrl + "/users"
        self.users = get_request(url)
        
    def checkUserPresent(self, userId):
        """Check if user is present"""
        self.loadUsers()
        for user in self.users:
            if user["userId"] == userId:
                return True
        return False
    def checkPlantPresent(self,userId, plantCode):
        """CHeck if plant is present"""
        self.loadUsers()
        for user in self.users:
            if user["userId"] == userId:
                for plant in user["plants"]:
                    if plant == plantCode:
                        return True
        return False
                
    def start(self):
        conf={
            '/':{
            'request.dispatch':cherrypy.dispatch.MethodDispatcher(),
            'tools.sessions.on':True
            }
        }
        cherrypy.tree.mount(self,'/',conf)
        cherrypy.config.update({'server.socket_port': self.port})
        cherrypy.config.update({'server.socket_host':'0.0.0.0'})
        cherrypy.engine.start()
        #cherrypy.engine.block()
        
    def stop(self):
        pass
        
    def GET(self,*uri,**params):
        """Get data from InfluxDB"""
        #http://localhost:8080/getData/userId/plantCode?measurament=humidity&duration=1 
        if len(uri)!=0:
            if uri[0] == "getData":
                if self.checkUserPresent(uri[1]):
                    if self.checkPlantPresent(uri[1],uri[2]): 
                        if params["measurament"] in self.possServices:
                            try:
                                duration = int(params["duration"])
                            except:
                                raise cherrypy.HTTPError("400", "invalid duration")
                            if self.test == 1:
                                timeInterval = "m"
                            else:
                                timeInterval = "h"
                            bucket = uri[1]
                            query = f'from(bucket: "{bucket}") \
                                |> range(start: -{duration}{timeInterval}) \
                                    |> filter(fn: (r) => r["_measurement"] == "{uri[2]}") \
                                        |> filter(fn: (r) => r["_field"] == "{params["measurament"]}")'
                            tables = self.client.query_api().query(org=self.org, query=query)
                            out = []
                            for table in tables:
                                for row in table.records:
                                    line = {"t": row.get_time().strftime("%m/%d/%Y, %H:%M:%S"), "v": row.get_value()}
                                    out.append(line)
                            return json.dumps(out)
                    else:
                        raise cherrypy.HTTPError("400", "Invalid plantCode")                    
                else:
                    raise cherrypy.HTTPError("400", "Invalid User")
            else:
                raise cherrypy.HTTPError("400", "Invalid operation")
        else:
            raise cherrypy.HTTPError("400", "no uri")

    def PUT(self,*uri,**params):
        return  
    
    def POST(self,*uri,**params):
        """Add user bucket"""
        if uri[0] == "addUser":
            body = json.loads(cherrypy.request.body.read())  # Read body data
            self.addUserBuckets(body["userId"])
            response = {"status": "OK", "code": 200}
            return response 
    def DELETE(self,*uri,**params):
        """Delete user bucket"""
        if uri[0] == "deleteUser":
            self.deleteUserBuckets(uri[1])
            print(f"Deleted {uri[1]}'s buckets")
            response = {"status": "OK", "code": 200}
            return response   

    def addUserBuckets(self, userID):  
        "Function that adds bucket to Influx"
        retention_rules = BucketRetentionRules(type="expire", every_seconds=2592000)
        created_bucket = self.bucket_api.create_bucket(bucket_name=f"{userID}", retention_rules = retention_rules,org = self.org)
        print(created_bucket)
        
    def listBuckets(self):
        """Get list of buckets from Influx"""
        buckets = self.bucket_api.find_buckets().buckets
        return buckets
    
    def deleteUserBuckets(self, userID):
        """Delete buket from Influx"""
        buckets = self.listBuckets()
        for bucket in buckets:
            if bucket.name.startswith(userID):
                self.bucket_api.delete_bucket(bucket)
                print(f"Succesfully deleted bucket: {bucket.name}")

class MySubscriber:
        def __init__(self, clientID, topic, broker, port, write_api):
            self.clientID = clientID
            self._paho_mqtt = PahoMQTT.Client(clientID, False) 
            self._paho_mqtt.on_connect = self.myOnConnect
            self._paho_mqtt.on_message = self.myOnMessageReceived 
            self.write_api = write_api
            self.topic = topic
            self.messageBroker = broker
            self.port = port
            with open(SETTINGS, 'r') as file:
                data = json.load(file)
            self.services2register = data["services4db"]
            self.org = data["influx_org"]
            self.registry_url = data["registry_url"]
            url = self.registry_url + "/users"
            self.users = get_request(url)
            self.time = time.time()

        def update_users(self):
            url = self.registry_url + "/users"
            self.users = get_request(url)

        def start (self):
            #manage connection to broker
            self._paho_mqtt.connect(self.messageBroker, self.port)
            self._paho_mqtt.loop_start()
            # subscribe for a topic
            self._paho_mqtt.subscribe(self.topic, 2)

        def stop (self):
            self._paho_mqtt.unsubscribe(self.topic)
            self._paho_mqtt.loop_stop()
            self._paho_mqtt.disconnect()

        def myOnConnect (self, paho_mqtt, userdata, flags, rc):
            print ("Connected to %s with result code: %d" % (self.messageBroker, rc))
            
        def checkUserPlantPresence(self, userId, plantCode):
            """Update users only after 10 seconds"""
            if time.time() > self.time + 10:
                self.update_users()
                self.time = time.time()
            for user in self.users:
                if user["userId"] == userId:
                    for plant in user["plants"]:
                        if plant == plantCode:
                            return True
            return False
        
        def checkBnNotAlive(self, bn):
            aliveMessages = ["updateCatalogDevice", "updateCatalogService"]
            if bn in aliveMessages:
                return False
            else:
                return True
            
            
        def myOnMessageReceived (self, paho_mqtt , userdata, msg):
            """Check it the message recived can be registered into DB adn write it"""
            if len(msg.topic.split("/")) > 3:
                userId = msg.topic.split("/")[1]
                plantCode = msg.topic.split("/")[2]
                service = msg.topic.split("/")[3]
                msgJson = json.loads(msg.payload)                
                if service in self.services2register and self.checkUserPlantPresence(userId, plantCode) and self.checkBnNotAlive(msgJson["bn"]):
                    converted = senmlToInflux(msgJson, plantCode)
                    for c in converted:
                        print(c)                
                        self.write_api.write(bucket=userId, org=self.org, record= c)

# Threads
class MQTTreciver(threading.Thread):
    """Subscriber that uploads messages into DB and sends alive messages"""
    def __init__(self, ThreadID, name):
        """Initialise thread widh ID and name."""
        threading.Thread.__init__(self)
        self.ThreadID = ThreadID
        self.name = name
        with open(SETTINGS, 'r') as file:
            data = json.load(file)
        self.topic = data["base_topic"]
        self.broker = data["messageBroker"]
        self.mqtt_port = int(data["brokerPort"])
        self.client = InfluxDBClient(url=data["url_db"], token=data["influx_token"])
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
        self.alive_topic = data["alive_topic"]
        self.url = data["adaptor_url"]

    def run(self):
        """Run thread."""
        global time_flag
        print(self.topic)
        # Start subscriber.
        sub = MySubscriber("123321", self.topic, self.broker, self.mqtt_port, self.write_api)
        print("Starting subscriber")
        sub.start()
        self.pub = MyPublisher("322228", self.alive_topic)
        print("Starting publisher")
        self.pub.start()  

        while True:
            print("sending alive message...")
            msg = {"bn": "updateCatalogService", "e":[{"n": "adaptor", "t": time.time(), "u": "URL", "v": self.url}]}
            self.pub.myPublish(json.dumps(msg), self.alive_topic)
            time.sleep(10)

class MyPublisher:
    def __init__(self, clientID, topic):
        self.clientID = clientID
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
        print ("Connected to %s with result code: %d" % (self.messageBroker, rc))

if __name__ == '__main__':
    adaptor = Adaptor()
    adaptor.start()
    
    reciver = MQTTreciver(2, "mqttReciver")
    reciver.run()
