import json
import cherrypy
import time
import requests
import threading
import paho.mqtt.client as PahoMQTT
from pathlib import Path

P = Path(__file__).parent.absolute()
CATALOG = P / 'catalog.json'
SETTINGS = P / 'settings.json'
INDEX = P / 'index.html'
MAXDELAY_DEVICE = 60
MAXDELAY_SERVICE = 60

"""Catalog class that interacts with the catalog.json file"""
class Catalog(object):
    def __init__(self):
        self.filename_catalog = CATALOG
        self.load_file()
    
    def load_file(self):
        for i in range(10):
            try:
                with open(self.filename_catalog, "r") as fs:                
                    self.catalog = json.loads(fs.read())
                return            
            except Exception:
                print("Problem in loading catalog")

    def write_catalog(self):
        """Write data on catalog json file."""
        with open(self.filename_catalog, "w") as fs:
            json.dump(self.catalog, fs, ensure_ascii=False, indent=2)
            fs.write("\n")

    def add_device(self, device_json, user):
        self.load_file()
        flag = 0
        for dev in self.catalog["devices"]:
            if dev["deviceID"] == device_json["deviceID"]:
                flag = 1
        if flag == 0:
            device_res_json = {
                "deviceID": device_json["deviceID"],
                "Services": device_json["Services"],
                "lastUpdate": time.time()
            }
            self.catalog["devices"].append(device_res_json)
        self.write_catalog()

    def add_service(self, service_json , user):
        self.load_file()
        flag = 0
        for service in self.catalog["services"]:
            if service["serviceID"] == service_json["serviceID"]:
                flag = 1
        if flag == 0:
            service_res_json = {
                "serviceID": service_json["serviceID"],
                "lastUpdate": time.time()
            }
            self.catalog["services"].append(service_res_json)
        self.write_catalog()

    def add_user(self, user_json):
        self.load_file()
        found = 0
        for user in self.catalog["users"]:
            if user["userId"] == user_json["userId"]:
                found = 1
        if found == 0:
            user_json = {
                "userId": user_json["userId"],
                "password": user_json["password"],
                "chatID": user_json["chatID"],
                "plants": []
            }
            self.catalog["users"].append(user_json)
            self.write_catalog()
            return "Added user"
        else:
            return "User already registered"

    def remove_user(self, userId):
        self.load_file()
        found = 0
        index = 0
        for user in self.catalog["users"]:
            if user["userId"] == userId:
                found = 1
                for plant in user["plants"]:
                    self.removeFromPlants(plant)
                del self.catalog["users"][index]
                self.write_catalog()
            index += 1
        if found == 0:
            return "User not found"
            
    def add_plant(self, plant_json):
        self.load_file()
        found = 0
        foundP = 0
        validCode = False
        for mod in self.catalog["models"]:
            if plant_json["plantCode"].startswith(mod["model_code"]):
                validCode = True
        if not validCode:
            return "Invalid plant code"
        for user in self.catalog["users"]:
            if user["userId"] == plant_json["userId"]:
                found = 1
                for plant in user["plants"]:
                    if plant == plant_json["plantCode"]:
                        foundP = 1
                        return "Plant already registered"
                if foundP == 0:
                    plant_res ={
                        "userId": plant_json["userId"],
                        "plantId": plant_json["plantId"],
                        "plantCode": plant_json["plantCode"],
                        "type": plant_json["type"],
                        "state": "auto",
                        "auto_init": "08:00",
                        "auto_end": "20:00",
                        "manual_init": "00:00",
                        "manual_end": "00:00",
                        "report_frequency": "daily"
                    }
                    user["plants"].append(plant_json["plantCode"])
                    self.catalog["plants"].append(plant_res)
                    self.write_catalog()
                    return "done"
        if found == 0:
            return "User not found"

    def removeFromPlants(self, plantCode):
        """Remove the plant also into catalog['plants']"""
        index = 0
        for plant in self.catalog["plants"]:
            if plant["plantCode"] == plantCode:
                del self.catalog["plants"][index]
            index +=1

    def remove_plant(self, userId, plantCode):
        self.load_file()
        found = 0
        foundP = 0
        for user in self.catalog["users"]:
            if user["userId"] == userId:
                found = 1
                for plant in user["plants"]:
                    if plant == plantCode:
                        foundP = 1
                        user["plants"].remove(plant)
                        self.removeFromPlants(plantCode)
                        self.write_catalog()
                        return "Plant removed"
                if foundP == 0:
                    return "Plant not found"
        if found == 0:
            return "User not found"

    def update_device(self, deviceJson):
        """Update timestamp of a devices."""
        self.load_file()
        found = 0
        for dev in self.catalog['devices']:
            if dev['deviceID'] == deviceJson["n"]:
                found = 1
                print("Updating %s timestamp." % dev['deviceID'])
                dev['lastUpdate'] = deviceJson["t"]    
        if not found:# Insert again the device
            print("not found")
            device_json = {
                "deviceID": deviceJson["n"],
                "netType": deviceJson["u"],
                "route": deviceJson["v"],
                "lastUpdate": deviceJson["t"]
            }
            self.catalog["devices"].append(device_json)
        self.write_catalog()

    def update_service(self, serviceJson):
        """Update timestamp of a services."""
        self.load_file()
        found = 0
        for service in self.catalog['services']:
            if service['serviceID'] == serviceJson["n"]:
                found = 1
                print("Updating %s timestamp." % service['serviceID'])
                service['lastUpdate'] = serviceJson["t"]    
        if not found:# Insert again the device
            print("not found")
            service_json = {
                "serviceID": serviceJson["n"],
                "netType": serviceJson["u"],
                "route": serviceJson["v"],
                "lastUpdate": serviceJson["t"]
            }
            self.catalog["services"].append(service_json)
        self.write_catalog()

    
    def remove_old_device(self):
        """Remove old devices whose timestamp is expired."""
        self.load_file()
        removable = []
        for counter, d in enumerate(self.catalog['devices']):
            if time.time() - float(d['lastUpdate']) > MAXDELAY_DEVICE:
                print("Removing... %s" % (d['deviceID']))
                removable.append(counter)
        for index in sorted(removable, reverse=True):
                del self.catalog['devices'][index]
        self.write_catalog()
        
    def remove_old_service(self):
        """Remove old services whose timestamp is expired."""
        self.load_file()
        removable = []
        for counter, s in enumerate(self.catalog['services']):
            if time.time() - float(s['lastUpdate']) > MAXDELAY_SERVICE:
                print("Removing... %s" % (s['serviceID']))
                removable.append(counter)
        for index in sorted(removable, reverse=True):
                del self.catalog['services'][index]
        self.write_catalog()

class Webserver(object):
    """CherryPy webserver."""
    exposed = True
    def start(self):
        conf={
            '/':{
            'request.dispatch':cherrypy.dispatch.MethodDispatcher(),
            'tools.sessions.on':True
            }
        }
        cherrypy.tree.mount(self,'/',conf)
        cherrypy.config.update({'server.socket_port':8081})
        cherrypy.config.update({'server.socket_host':'0.0.0.0'})
        cherrypy.engine.start()
        try:
            with open(SETTINGS, "r") as fs:                
                self.settings = json.loads(fs.read())   
            self.cat = Catalog()
        except Exception:
            print("Problem in loading settings")

    def GET(self, *uri, **params):
        self.cat.load_file()
        if len(uri) == 0:
            return open(INDEX)
        else:
            #GET Devices from catalog            
            if uri[0] == 'devices':
                return json.dumps(self.cat.catalog["devices"])
            #GET Services from catalog    
            if uri[0] == 'services':
                return json.dumps(self.cat.catalog["services"])
            #GET Users from catalog    
            if uri[0] == 'users':
                return json.dumps(self.cat.catalog["users"])
            #GET Models from catalog    
            if uri[0] == 'models':
                return json.dumps(self.cat.catalog["models"])
            #GET Plants from catalog    
            if uri[0] == 'plants':
                return json.dumps(self.cat.catalog["plants"])
            #GET PlantTypes from catalog    
            if uri[0] == 'valid_plant_types':
                return json.dumps(self.cat.catalog["valid_plant_types"])
        

    def POST(self, *uri, **params):
        """Define POST HTTP method for RESTful webserver.Modify content of catalogs"""  
        
        self.cat.load_file()
        if uri[0] == 'addd':
            # Add new device.
            body = json.loads(cherrypy.request.body.read())  # Read body data
            self.cat.add_device(body, uri[1])#(device, user)
            return 200
        
        if uri[0] == 'adds':
            # Add new service.
            body = json.loads(cherrypy.request.body.read())  # Read body data
            self.cat.add_service(body, uri[1])
            return 200
        if uri[0] == 'addu':
            # Add new user.
            body = json.loads(cherrypy.request.body.read())  # Read body {userid, password}
            out = self.cat.add_user(body)
            if out == "User already registered":
                response = {"status": "NOT_OK",
                            "code": 400}
                #raise cherrypy.HTTPError("400", "User already registered")
                return json.dumps(response)
            else:
                headers = {'content-type': 'application/json; charset=UTF-8'}
                response = requests.post(self.settings["adaptor_url"] + "/addUser", data=json.dumps(body), headers=headers)
                response = {"status": "OK", "code": 200, "message": "Data processed"}
                return json.dumps(response)
                
        if uri[0] == 'addp':
            # Add new plant.
            body = json.loads(cherrypy.request.body.read())  # Read body data
            out = self.cat.add_plant(body)
            if out == "Plant already registered":
                response = {"status": "NOT_OK", "code": 400, "message": "Plant already registered"}
                return json.dumps(response)
            elif out == "User not found":
                response = {"status": "NOT_OK", "code": 400, "message": "User not found"}
                return json.dumps(response)
            elif out == "done":
                response = {"status": "OK", "code": 200, "message": "Plant registered successfully"}
                return json.dumps(response)
            elif out == "Invalid plant code":
                response = {"status": "NOT_OK", "code": 400, "message": "Invalid plant code"}
                return json.dumps(response)
    def PUT(self, *uri, **params):
        self.cat.load_file()
        if uri[0] == 'updateInterval':
            #update intervals and mode of a specific plant
            body = json.loads(cherrypy.request.body.read())  # Read body data
            plantCode = body["plantCode"]
            state = body["state"]
            init = body["init"]
            end = body["end"]
            found = False
            output = ""
            for plant in self.cat.catalog["plants"]:
                if plant["plantCode"] == plantCode:
                    found = True
                    if state == "auto":
                        plant['state']="auto"
                        plant["auto_init"] = init
                        plant["auto_end"] = end
                        self.cat.write_catalog()
                    elif state == "manual":
                        plant['state']="manual"
                        plant["manual_init"] = init
                        plant["manual_end"] = end
                        self.cat.write_catalog()
                    else:
                        output = "Invalid state"
            if not found:   
                response = {"status": "NOT_OK", "code": 400, "message": "Invalid plant code"}
            elif output != "":
                response = {"status": "NOT_OK", "code": 400, "message": output}  
            else:
                response = {"status": "OK", "code": 200, "message": "Data updated successfully"}
            return json.dumps(response)
        
        elif uri[0] == 'modifyPlant':
            #Update plant data
            body = json.loads(cherrypy.request.body.read())  # Read body data
            plantCode = body["plantCode"]
            newplantId = body["new_name"]
            found = False
            for plant in self.cat.catalog["plants"]:
                if plant["plantCode"] == plantCode:
                    found = True
                    index = self.cat.catalog["plants"].index(plant)
            self.cat.catalog['plants'][index]['plantId'] = newplantId 
            self.cat.write_catalog()
            if not found:   
                response = {"status": "NOT_OK", "code": 400, "message": "Invalid plant code"}
            else:
                response = {"status": "OK", "code": 200, "message": "Data updated successfully"}
            return json.dumps(response)
        elif uri[0] == 'setreportfrequency':
            #Update the frequency of the report
            body = json.loads(cherrypy.request.body.read())  # Read body data
            plantCode = body['plantCode']
            reportf = body['report_frequency']
            found = False
            for plant in self.cat.catalog['plants']:
                if plant['plantCode'] == plantCode:
                    found = True
                    plant['report_frequency'] = reportf
                    self.cat.write_catalog()
            if found:
                response = {"status": "OK", "code": 200, "message": "Data updated successfully"}
            else:
                response = {"status": "NOT_OK", "code": 400, "message": "Invalid plant code"}        
            return json.dumps(response) 
        elif uri[0] == "transferuser":
            #Update chatID for telegram 
            body = json.loads(cherrypy.request.body.read())
            found = False
            for user in self.cat.catalog['users']:
                if user['userId'] == body['userId']:
                    found = True
                    user['chatID'] = body['chatID']
                    self.cat.write_catalog()
            if found:
                response = {"status": "OK", "code": 200, "message": "Data updated successfully"}
            else:
                response = {"status": "NOT_OK", "code": 400, "message": "Invalid plant code"}   
            return json.dumps(response)
            
    def DELETE(self, *uri, **params):
        if uri[0] == 'rmu':
            out = self.cat.remove_user(uri[1])
            if out == "User not found":
                response = {"status": "NOT_OK","code": 400}
                return json.dumps(response)
            else:
                response = requests.delete(self.settings["adaptor_url"] + "/deleteUser/" + uri[1])
                response = {"status": "OK", "code": 200}
                return json.dumps(response)           
        elif uri[0] == 'rmp':
            out = self.cat.remove_plant(uri[1], uri[2])
            if out == "User not found":
                raise cherrypy.HTTPError("400", "user not found")
            if out == "Plant not found":
                raise cherrypy.HTTPError("400", "plant not found")
            else:
                result = {"status": "OK", "code": 200, "message": "Data processed"}
                return json.dumps(result)

class MySubscriber:
        def __init__(self, clientID, topic, broker, port):
            self.clientID = clientID
			# create an instance of paho.mqtt.client
            self._paho_mqtt = PahoMQTT.Client(clientID, False) 
            
			# register the callback
            self._paho_mqtt.on_connect = self.myOnConnect
            self._paho_mqtt.on_message = self.myOnMessageReceived 
            self.topic = topic
            self.messageBroker = broker
            self.port = port

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

        def myOnMessageReceived (self, paho_mqtt , userdata, msg):
            #Listening to all messages with topic "RootyPy/#"
            message = json.loads(msg.payload.decode("utf-8")) #{"bn": updateCatalog<>, "e": [{...}]}
            catalog = Catalog()
            if message['bn'] == "updateCatalogDevice":            
                catalog.update_device(message['e'][0])# {"n": PlantCode/deviceName, "t": time.time(), "v": "", "u": IP}
            if message['bn'] == "updateCatalogService":            
                catalog.update_service(message['e'][0])# {"n": serviceName, "t": time.time(), "v": "", "u": IP}


# Threads
class First(threading.Thread):
    """Thread to run CherryPy webserver."""
    exposed=True
    def __init__(self, ThreadID, name):
        """Initialise thread widh ID and name."""
        threading.Thread.__init__(self)
        self.ThreadID = ThreadID
        self.name = name
        self.webserver = Webserver()
        self.webserver.start()
        

class Second(threading.Thread):
    """MQTT Thread."""

    def __init__(self, ThreadID, name):
        """Initialise thread widh ID and name."""
        threading.Thread.__init__(self)
        self.ThreadID = ThreadID
        self.name = name
        with open(SETTINGS, 'r') as file:
            data = json.load(file)
        self.topic = data["base_topic"]
        self.broker = data["broker"]
        self.mqtt_port = int(data["port"])

    def run(self):
        """Run thread."""
        cat = Catalog()
        cat.load_file()
        sub = MySubscriber("registry_sub", self.topic, self.broker, self.mqtt_port)
        sub.loop_flag = 1
        sub.start()

        while sub.loop_flag:
            time.sleep(1)

        while True:
            time.sleep(1)

        sub.stop()

class Third(threading.Thread):
    """Old device remover thread.
    Remove old devices which do not send alive messages anymore.
    Devices are removed every five minutes.
    """

    def __init__(self, ThreadID, name):
        """Initialise thread widh ID and name."""
        threading.Thread.__init__(self)
        self.ThreadID = ThreadID
        self.name = name

    def run(self):
        """Run thread."""
        time.sleep(MAXDELAY_DEVICE+1)
        while True:
            cat = Catalog()
            cat.remove_old_device()
            time.sleep(MAXDELAY_DEVICE+1)
            
class Fourth(threading.Thread):
    """Old service remover thread.
    Remove old services which do not send alive messages anymore.
    Services are removed every five minutes.
    """

    def __init__(self, ThreadID, name):
        """Initialise thread widh ID and name."""
        threading.Thread.__init__(self)
        self.ThreadID = ThreadID
        self.name = name

    def run(self):
        """Run thread."""
        time.sleep(MAXDELAY_SERVICE+1)
        while True:
            cat = Catalog()
            cat.remove_old_service()
            time.sleep(MAXDELAY_SERVICE+1)

#Main

def main():
    """Start all threads."""
    thread1 = First(1, "CherryPy")
    thread2 = Second(2, "Updater")
    thread3 = Third(3, "RemoverDevices")
    thread4 = Fourth(4, "RemoverServices")

    print("> Starting CherryPy...")
    thread1.start()

    time.sleep(1)
    print("\n> Starting MQTT device updater...")
    thread2.start()

    time.sleep(1)
    print("\n> Starting Device remover...\nDelete old devices every %d seconds."% MAXDELAY_DEVICE)
    thread3.start()
    
    time.sleep(1)
    print("\n> Starting Service remover...\nDelete old devices every %d seconds."% MAXDELAY_SERVICE)
    thread4.start()

if __name__ == '__main__':
    main()
